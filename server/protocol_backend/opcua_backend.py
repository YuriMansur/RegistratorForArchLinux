"""
OpcUaBackend — менеджер нескольких OPC UA серверов.
PyQt6 не используется — коммуникация через Python callable callbacks.
"""
import logging
from typing import Dict, Optional, Callable, Any, List
from protocol_backend.thread.opcua.opcua_worker_thread import OpcUaWorkerThread

log = logging.getLogger(__name__)


class OpcUaBackend:
    """
    Управляет пулом OpcUaWorkerThread'ов.
    Внешний API — публичные on_* callbacks:

        backend.on_connected    = lambda srv: ...
        backend.on_data_updated = lambda srv, nid, val: ...
    """

    def __init__(self):
        self.servers: Dict[str, dict] = {}

        # ── Публичные callbacks ───────────────────────────────────────────────
        self.on_connected:           Optional[Callable[[str], None]]           = None
        self.on_disconnected:        Optional[Callable[[str], None]]           = None
        self.on_connection_error:    Optional[Callable[[str, str], None]]      = None
        self.on_data_updated:        Optional[Callable[[str, str, Any], None]] = None
        self.on_tag_subscribed:      Optional[Callable[[str, str], None]]      = None
        self.on_watchdog_disconnect: Optional[Callable[[str], None]]           = None

    # ── Server management ─────────────────────────────────────────────────────

    def add_server(self, server_id: str, endpoint: str, namespace: int = 2, timeout: float = 10.0) -> bool:
        if server_id in self.servers:
            return False
        self.servers[server_id] = {
            "endpoint": endpoint, "namespace": namespace,
            "timeout": timeout, "thread": None,
        }
        return True

    def remove_server(self, server_id: str, force: bool = False) -> bool:
        if server_id not in self.servers:
            return False
        if self.is_connected(server_id):
            if not force:
                return False
            self.disconnect_server(server_id, blocking=True)
        del self.servers[server_id]
        return True

    def get_servers(self) -> Dict[str, dict]:
        return {
            sid: {"endpoint": s["endpoint"], "namespace": s["namespace"], "connected": self.is_connected(sid)}
            for sid, s in self.servers.items()
        }

    def is_connected(self, server_id: str) -> bool:
        server = self.servers.get(server_id)
        if not server:
            return False
        thread = server.get("thread")
        if thread and thread.is_alive():
            return thread.is_connected
        return False

    # ── Connection ────────────────────────────────────────────────────────────

    def connect_server(self, server_id: str) -> bool:
        if server_id not in self.servers:
            return False
        if self.is_connected(server_id):
            return True

        server = self.servers[server_id]
        thread = server.get("thread")
        is_running = thread.is_alive() if thread else False

        if not is_running:
            thread = OpcUaWorkerThread(
                server_id=server_id,
                endpoint=server["endpoint"],
                namespace=server["namespace"],
                timeout=server["timeout"],
            )
            self._connect_thread_callbacks(server_id, thread)
            server["thread"] = thread
            thread.on_loop_ready = lambda: thread.connect_to_server()
            thread.start()
        else:
            thread.connect_to_server()
        return True

    def disconnect_server(self, server_id: str, blocking: bool = False) -> bool:
        if server_id not in self.servers:
            return False
        if not self.is_connected(server_id):
            return True
        self.servers[server_id]["thread"].stop(blocking=blocking)
        return True

    def connect_all(self):
        for sid in self.servers:
            if not self.is_connected(sid):
                self.connect_server(sid)

    def disconnect_all(self, blocking: bool = False):
        threads = []
        for sid in list(self.servers):
            server = self.servers.get(sid)
            if server and self.is_connected(sid):
                server["thread"].stop(blocking=False)
                threads.append(server["thread"])
        if blocking:
            for t in threads:
                t.join(2.0)

    # ── Read / Write ──────────────────────────────────────────────────────────

    def read_node(self, server_id: str, node_id: str) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.read_node(node_id)
        return True

    def write_node(self, server_id: str, node_id: str, value: Any) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.write_node(node_id, value)
        return True

    def read_multiple_nodes(self, server_id: str, node_ids: List[str]) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.read_multiple_nodes(node_ids)
        return True

    def write_multiple_nodes(self, server_id: str, values: Dict[str, Any]) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.write_multiple_nodes(values)
        return True

    # ── Subscriptions ─────────────────────────────────────────────────────────

    def subscribe_tag(self, server_id: str, node_id: str, tag_name: Optional[str] = None) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.subscribe_tag(node_id, tag_name)
        return True

    def unsubscribe_tag(self, server_id: str, node_id: str) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.unsubscribe_tag(node_id)
        return True

    def subscribe_multiple_tags(self, server_id: str, tags: Dict[str, str]) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.subscribe_multiple_tags(tags)
        return True

    def get_subscribed_tags(self, server_id: str) -> List[str]:
        t = self._get_thread(server_id)
        return t.get_subscribed_tags() if t else []

    # ── Polling ───────────────────────────────────────────────────────────────

    def start_polling(self, server_id: str, name: str, node_ids: List[str],
                      interval: float = 1.0, sequential: bool = False) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.start_polling(name, node_ids, interval, sequential)
        return True

    def stop_polling(self, server_id: str, name: Optional[str] = None) -> bool:
        t = self._get_thread(server_id)
        if not t:
            return False
        t.stop_polling(name)
        return True

    def get_active_polls(self, server_id: str) -> Dict[str, Dict]:
        t = self._get_thread(server_id)
        return t.get_active_polls() if t else {}

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def start_watchdog(self, server_id: str, interval: float = 5.0) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.start_watchdog(interval)
        return True

    def stop_watchdog(self, server_id: str) -> bool:
        t = self._get_thread(server_id)
        if not t:
            return False
        t.stop_watchdog()
        return True

    def is_watchdog_active(self, server_id: str) -> bool:
        t = self._get_thread(server_id)
        return t.is_watchdog_active if t else False

    # ── Exploration ───────────────────────────────────────────────────────────

    def browse_nodes(self, server_id: str, start_node_id: Optional[str] = None, depth: int = 1) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.browse_nodes(start_node_id, depth)
        return True

    def read_node_info(self, server_id: str, node_id: str) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.read_node_info(node_id)
        return True

    def call_method(self, server_id: str, parent_node_id: str, method_node_id: str,
                    args: Optional[List] = None) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.call_method(parent_node_id, method_node_id, args)
        return True

    def discover_methods(self, server_id: str, object_node_id: str) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.discover_methods(object_node_id)
        return True

    def read_history(self, server_id: str, node_id: str, start_time=None,
                     end_time=None, num_values: int = 0) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.read_history(node_id, start_time, end_time, num_values)
        return True

    def read_history_multiple(self, server_id: str, node_ids: List[str],
                               start_time=None, end_time=None, num_values: int = 0) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.read_history_multiple(node_ids, start_time, end_time, num_values)
        return True

    def subscribe_events(self, server_id: str, source_node_id: Optional[str] = None) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.subscribe_events(source_node_id)
        return True

    def unsubscribe_events(self, server_id: str, source_node_id: Optional[str] = None) -> bool:
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        t.unsubscribe_events(source_node_id)
        return True

    # ── Data access ───────────────────────────────────────────────────────────

    def get_latest_data(self, server_id: str) -> Dict[str, Any]:
        t = self._get_thread(server_id)
        return t.get_latest_data() if t else {}

    def get_all_data(self) -> Dict[str, Dict[str, Any]]:
        return {sid: self.get_latest_data(sid) for sid in self.servers}

    def get_stats(self, server_id: str) -> Dict[str, Any]:
        t = self._get_thread(server_id)
        return t.get_stats() if t else {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def stop_all(self):
        self.disconnect_all(blocking=True)
        self.servers.clear()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_thread(self, server_id: str) -> Optional[OpcUaWorkerThread]:
        server = self.servers.get(server_id)
        return server.get("thread") if server else None

    def _get_connected_thread(self, server_id: str) -> Optional[OpcUaWorkerThread]:
        if not self.is_connected(server_id):
            return None
        return self.servers[server_id]["thread"]

    def _connect_thread_callbacks(self, server_id: str, thread: OpcUaWorkerThread):
        thread.on_connected      = lambda: self._on_server_connected(server_id)
        thread.on_disconnected   = lambda: self._on_server_disconnected(server_id)
        thread.on_connection_error = lambda err: self._on_server_error(server_id, err)
        thread.on_data_updated   = lambda nid, val: self._on_data_updated(server_id, nid, val)
        thread.on_tag_subscribed = lambda nid: self._on_tag_subscribed(server_id, nid)
        thread.on_watchdog_disconnect = lambda: self._on_watchdog_disconnect(server_id)

    def _on_server_connected(self, server_id: str):
        log.info("Connected: %s", server_id)
        if self.on_connected:
            self.on_connected(server_id)

    def _on_server_disconnected(self, server_id: str):
        log.warning("Disconnected: %s", server_id)
        if self.on_disconnected:
            self.on_disconnected(server_id)

    def _on_server_error(self, server_id: str, error: str):
        log.error("Error [%s]: %s", server_id, error)
        if self.on_connection_error:
            self.on_connection_error(server_id, error)

    def _on_data_updated(self, server_id: str, node_id: str, value: Any):
        if self.on_data_updated:
            self.on_data_updated(server_id, node_id, value)

    def _on_tag_subscribed(self, server_id: str, node_id: str):
        if self.on_tag_subscribed:
            self.on_tag_subscribed(server_id, node_id)

    def _on_watchdog_disconnect(self, server_id: str):
        if self.on_watchdog_disconnect:
            self.on_watchdog_disconnect(server_id)
