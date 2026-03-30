"""
OpcUaWorkerThread — threading.Thread обёртка для AsyncOpcUaWorker.
Каждый OPC UA сервер работает в отдельном потоке с собственным asyncio loop.
PyQt6 не используется — коммуникация через Python callable callbacks.
"""

import asyncio
import threading
import logging
from typing import Optional, Dict, Any, List, Callable

log = logging.getLogger(__name__)


def _call(cb: Optional[Callable], *args):
    """Безопасный вызов callback."""
    if cb:
        try:
            cb(*args)
        except Exception as e:
            log.error("Callback error: %s", e)


class OpcUaWorkerThread(threading.Thread):
    """
    threading.Thread обёртка для AsyncOpcUaWorker с собственным asyncio loop.

    Вместо Qt-сигналов используются callable-атрибуты on_*:
        thread.on_connected   = lambda: ...
        thread.on_data_updated = lambda node_id, val: ...
    """

    def __init__(
        self,
        server_id: str,
        endpoint: str,
        namespace: int = 2,
        timeout: float = 10.0,
    ):
        super().__init__(daemon=True, name=f"opcua-{server_id}")

        self.server_id  = server_id
        self.endpoint   = endpoint
        self.namespace  = namespace
        self.timeout    = timeout

        self.loop:   Optional[asyncio.AbstractEventLoop] = None
        self.worker: Optional[Any] = None

        self._connected         = False
        self._stopping          = False
        self._loop_ready        = False
        self._latest_data_lock  = threading.Lock()
        self._latest_data:      Dict[str, Any] = {}
        self._data_changed_flag = False

        # ── Callbacks (заменяют pyqtSignal) ──────────────────────────────────
        self.on_loop_ready:                  Optional[Callable]                  = None
        self.on_connected:                   Optional[Callable]                  = None
        self.on_disconnected:                Optional[Callable]                  = None
        self.on_connection_error:            Optional[Callable[[str], None]]     = None
        self.on_data_updated:                Optional[Callable[[str, Any], None]]= None
        self.on_tag_subscribed:              Optional[Callable[[str], None]]     = None
        self.on_tag_unsubscribed:            Optional[Callable[[str], None]]     = None
        self.on_read_completed:              Optional[Callable[[str, Any], None]]= None
        self.on_write_completed:             Optional[Callable[[str, bool], None]]= None
        self.on_batch_read_completed:        Optional[Callable[[dict], None]]    = None
        self.on_batch_write_completed:       Optional[Callable[[dict], None]]    = None
        self.on_watchdog_disconnect:         Optional[Callable]                  = None
        self.on_browse_completed:            Optional[Callable[[list], None]]    = None
        self.on_node_info_completed:         Optional[Callable[[dict], None]]    = None
        self.on_method_completed:            Optional[Callable[[Any], None]]     = None
        self.on_methods_discovered:          Optional[Callable[[list], None]]    = None
        self.on_history_completed:           Optional[Callable[[str, list], None]]= None
        self.on_history_multiple_completed:  Optional[Callable[[dict], None]]    = None
        self.on_event_received:              Optional[Callable[[dict], None]]    = None

    # ── Thread lifecycle ──────────────────────────────────────────────────────

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.set_debug(False)

        from protocol_backend.protocol_client.opcua.opcua_worker.opcua_worker import AsyncOpcUaWorker

        self.worker = AsyncOpcUaWorker(
            endpoint=self.endpoint,
            namespace=self.namespace,
            timeout=self.timeout,
            on_data_changed=self._on_data_changed,
        )

        self._loop_ready = True
        _call(self.on_loop_ready)

        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def stop(self, blocking: bool = False):
        if self._stopping:
            return
        self._stopping = True

        if self.loop and self.worker:
            future = asyncio.run_coroutine_threadsafe(
                self._async_shutdown(), self.loop
            )
            if blocking:
                try:
                    future.result(timeout=2.0)
                except Exception:
                    pass

        if blocking:
            self.join(2.0)

    def is_loop_ready(self) -> bool:
        return self._loop_ready and self.loop is not None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect_to_server(self):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_connect(), self.loop)

    async def _async_connect(self):
        try:
            success = await self.worker.connect()
            if success:
                self._connected = True
                _call(self.on_connected)
        except Exception as e:
            _call(self.on_connection_error, str(e))

    async def _async_disconnect(self):
        try:
            await self.worker.disconnect()
            self._connected = False
            _call(self.on_disconnected)
        except Exception as e:
            _call(self.on_connection_error, str(e))

    async def _async_shutdown(self):
        if self._connected:
            try:
                await self.worker.disconnect()
                self._connected = False
                _call(self.on_disconnected)
            except Exception as e:
                _call(self.on_connection_error, str(e))
        self.loop.stop()

    # ── Read / Write ──────────────────────────────────────────────────────────

    def read_node(self, node_id: str):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_read_node(node_id), self.loop)

    async def _async_read_node(self, node_id: str):
        try:
            value = await self.worker.read_node(node_id)
            _call(self.on_read_completed, node_id, value)
        except Exception as e:
            _call(self.on_connection_error, f"Read error: {e}")

    def write_node(self, node_id: str, value: Any):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_write_node(node_id, value), self.loop)

    async def _async_write_node(self, node_id: str, value: Any):
        try:
            success = await self.worker.write_node(node_id, value)
            _call(self.on_write_completed, node_id, success)
        except Exception as e:
            _call(self.on_connection_error, f"Write error: {e}")
            _call(self.on_write_completed, node_id, False)

    def read_multiple_nodes(self, node_ids: List[str]):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_read_multiple_nodes(node_ids), self.loop)

    async def _async_read_multiple_nodes(self, node_ids: List[str]):
        try:
            results = await self.worker.read_multiple_nodes(node_ids)
            _call(self.on_batch_read_completed, results)
        except Exception as e:
            _call(self.on_connection_error, f"Batch read error: {e}")

    def write_multiple_nodes(self, values: Dict[str, Any]):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_write_multiple_nodes(values), self.loop)

    async def _async_write_multiple_nodes(self, values: Dict[str, Any]):
        try:
            results = await self.worker.write_multiple_nodes(values)
            _call(self.on_batch_write_completed, results)
        except Exception as e:
            _call(self.on_connection_error, f"Batch write error: {e}")

    # ── Subscriptions ─────────────────────────────────────────────────────────

    def subscribe_tag(self, node_id: str, tag_name: Optional[str] = None):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_subscribe_tag(node_id, tag_name), self.loop)

    async def _async_subscribe_tag(self, node_id: str, tag_name: Optional[str]):
        try:
            success = await self.worker.subscribe_tag(node_id, tag_name)
            if success:
                _call(self.on_tag_subscribed, node_id)
        except Exception as e:
            _call(self.on_connection_error, f"Subscribe error: {e}")

    def unsubscribe_tag(self, node_id: str):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_unsubscribe_tag(node_id), self.loop)

    async def _async_unsubscribe_tag(self, node_id: str):
        try:
            success = await self.worker.unsubscribe_tag(node_id)
            if success:
                _call(self.on_tag_unsubscribed, node_id)
        except Exception as e:
            _call(self.on_connection_error, f"Unsubscribe error: {e}")

    def subscribe_multiple_tags(self, tags: Dict[str, str]):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_subscribe_multiple_tags(tags), self.loop)

    async def _async_subscribe_multiple_tags(self, tags: Dict[str, str]):
        try:
            results = await self.worker.subscribe_multiple_tags(tags)
            for tag_name, success in results.items():
                if success:
                    _call(self.on_tag_subscribed, tags[tag_name])
        except Exception as e:
            _call(self.on_connection_error, f"Subscribe multiple error: {e}")

    # ── Polling ───────────────────────────────────────────────────────────────

    def start_polling(self, name: str, node_ids: List[str], interval: float = 1.0, sequential: bool = False):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(
            self.worker.start_polling(name, node_ids, interval, sequential), self.loop
        )

    def stop_polling(self, name: Optional[str] = None):
        if not self.is_loop_ready():
            return
        asyncio.run_coroutine_threadsafe(self.worker.stop_polling(name), self.loop)

    def get_active_polls(self) -> Dict[str, Dict]:
        if not self.worker:
            return {}
        return self.worker.get_active_polls()

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def start_watchdog(self, interval: float = 5.0):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_start_watchdog(interval), self.loop)

    async def _async_start_watchdog(self, interval: float):
        await self.worker.start_watchdog(interval)
        asyncio.ensure_future(self._sync_watchdog_state())

    async def _sync_watchdog_state(self):
        while self.worker and self.worker.is_watchdog_active:
            await asyncio.sleep(0.5)
        if self.worker and not self.worker.is_connected and self._connected:
            self._connected = False
            _call(self.on_watchdog_disconnect)
            _call(self.on_disconnected)

    def stop_watchdog(self):
        if not self.is_loop_ready():
            return
        asyncio.run_coroutine_threadsafe(self.worker.stop_watchdog(), self.loop)

    @property
    def is_watchdog_active(self) -> bool:
        return self.worker.is_watchdog_active if self.worker else False

    # ── Exploration ───────────────────────────────────────────────────────────

    def browse_nodes(self, start_node_id: Optional[str] = None, depth: int = 1):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_browse_nodes(start_node_id, depth), self.loop)

    async def _async_browse_nodes(self, start_node_id, depth):
        try:
            result = await self.worker.browse_nodes(start_node_id, depth)
            _call(self.on_browse_completed, result)
        except Exception as e:
            _call(self.on_connection_error, f"Browse error: {e}")

    def read_node_info(self, node_id: str):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_read_node_info(node_id), self.loop)

    async def _async_read_node_info(self, node_id: str):
        try:
            result = await self.worker.read_node_info(node_id)
            _call(self.on_node_info_completed, result)
        except Exception as e:
            _call(self.on_connection_error, f"Read node info error: {e}")

    def call_method(self, parent_node_id: str, method_node_id: str, args: Optional[List] = None):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(
            self._async_call_method(parent_node_id, method_node_id, args), self.loop
        )

    async def _async_call_method(self, parent_node_id, method_node_id, args):
        try:
            result = await self.worker.call_method(parent_node_id, method_node_id, args)
            _call(self.on_method_completed, result)
        except Exception as e:
            _call(self.on_connection_error, f"Method call error: {e}")

    def discover_methods(self, object_node_id: str):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_discover_methods(object_node_id), self.loop)

    async def _async_discover_methods(self, object_node_id: str):
        try:
            result = await self.worker.discover_methods(object_node_id)
            _call(self.on_methods_discovered, result)
        except Exception as e:
            _call(self.on_connection_error, f"Discover methods error: {e}")

    def read_history(self, node_id: str, start_time=None, end_time=None, num_values: int = 0):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(
            self._async_read_history(node_id, start_time, end_time, num_values), self.loop
        )

    async def _async_read_history(self, node_id, start_time, end_time, num_values):
        try:
            result = await self.worker.read_history(node_id, start_time, end_time, num_values)
            _call(self.on_history_completed, node_id, result)
        except Exception as e:
            _call(self.on_connection_error, f"History read error: {e}")

    def read_history_multiple(self, node_ids: List[str], start_time=None, end_time=None, num_values: int = 0):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(
            self._async_read_history_multiple(node_ids, start_time, end_time, num_values), self.loop
        )

    async def _async_read_history_multiple(self, node_ids, start_time, end_time, num_values):
        try:
            result = await self.worker.read_history_multiple(node_ids, start_time, end_time, num_values)
            _call(self.on_history_multiple_completed, result)
        except Exception as e:
            _call(self.on_connection_error, f"History multiple read error: {e}")

    def subscribe_events(self, source_node_id: Optional[str] = None):
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_subscribe_events(source_node_id), self.loop)

    async def _async_subscribe_events(self, source_node_id):
        try:
            await self.worker.subscribe_events(
                source_node_id=source_node_id,
                event_callback=lambda event: _call(self.on_event_received, event),
            )
        except Exception as e:
            _call(self.on_connection_error, f"Subscribe events error: {e}")

    def unsubscribe_events(self, source_node_id: Optional[str] = None):
        if not self.is_loop_ready():
            return
        asyncio.run_coroutine_threadsafe(self.worker.unsubscribe_events(source_node_id), self.loop)

    # ── Data access ───────────────────────────────────────────────────────────

    def _on_data_changed(self, node_id: str, value: Any):
        with self._latest_data_lock:
            self._latest_data[node_id] = value
            self._data_changed_flag = True
        _call(self.on_data_updated, node_id, value)

    def get_latest_data(self) -> Dict[str, Any]:
        with self._latest_data_lock:
            return self._latest_data.copy()

    def has_data_changed(self) -> bool:
        with self._latest_data_lock:
            if self._data_changed_flag:
                self._data_changed_flag = False
                return True
        return False

    @property
    def is_connected(self) -> bool:
        if self.worker:
            return self.worker.is_connected
        return self._connected

    def get_subscribed_tags(self) -> List[str]:
        if not self.worker:
            return []
        return self.worker.get_subscribed_tags()

    def get_stats(self) -> Dict[str, Any]:
        if not self.worker:
            return {}
        return self.worker.get_stats()
