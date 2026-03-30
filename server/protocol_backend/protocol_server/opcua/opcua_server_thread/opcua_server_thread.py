"""
OpcUaServerThread — threading.Thread обёртка для AsyncOpcUaServer.

Запускает asyncio event loop в отдельном потоке.
Все операции с сервером (add_variable, write_value) выполняются
через run_coroutine_threadsafe — безопасно из любого потока.

Пример:
    thread = OpcUaServerThread(endpoint="opc.tcp://0.0.0.0:4841")
    thread.on_started = lambda: print("server ready")
    thread.start()

    # Из основного потока:
    node = thread.add_variable("Temperature", 20.0)
    thread.write_value(node, 25.5)
    thread.stop()
"""

import asyncio
import logging
import threading
from typing import Any, Callable, Optional

from protocol_backend.protocol_server.opcua.opcua_server.opcua_server import AsyncOpcUaServer

log = logging.getLogger(__name__)


class OpcUaServerThread(threading.Thread):
    """
    threading.Thread обёртка для AsyncOpcUaServer с собственным asyncio loop.

    Колбэки (устанавливаются до start()):
        on_started              — сервер принимает соединения
        on_stopped              — сервер остановлен
        on_client_connected     — (addr: str)
        on_client_disconnected  — (addr: str)
    """

    on_started:              Optional[Callable[[], None]]    = None
    on_stopped:              Optional[Callable[[], None]]    = None
    on_client_connected:     Optional[Callable[[str], None]] = None
    on_client_disconnected:  Optional[Callable[[str], None]] = None

    def __init__(
        self,
        endpoint:     str = "opc.tcp://0.0.0.0:4841",
        namespace:    str = "urn:registrator:server",
        server_name:  str = "Registrator OPC UA Server",
        **kwargs,
    ):
        super().__init__(daemon=True, name="opcua-server", **kwargs)
        self.endpoint    = endpoint
        self.namespace   = namespace
        self.server_name = server_name

        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[AsyncOpcUaServer]          = None
        self._ready   = threading.Event()
        self._stop_event = asyncio.Event()

    # ── Thread entry ──────────────────────────────────────────────────────────

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception:
            log.exception("OpcUaServerThread error")
        finally:
            self._loop.close()

    async def _main(self) -> None:
        self._stop_event = asyncio.Event()
        self._server = AsyncOpcUaServer(
            endpoint=self.endpoint,
            namespace=self.namespace,
            server_name=self.server_name,
        )
        # Пробрасываем колбэки
        self._server.on_started             = self._on_started
        self._server.on_stopped             = self.on_stopped
        self._server.on_client_connected    = self.on_client_connected
        self._server.on_client_disconnected = self.on_client_disconnected

        await self._server.start()
        self._ready.set()
        await self._stop_event.wait()     # ждём сигнала остановки
        await self._server.stop()

    def _on_started(self) -> None:
        if self.on_started:
            try:
                self.on_started()
            except Exception as e:
                log.error("on_started callback error: %s", e)

    # ── Публичный API (thread-safe) ────────────────────────────────────────────

    def stop(self) -> None:
        """Остановить сервер и поток."""
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self.join(timeout=5.0)

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Подождать пока сервер не будет готов принимать соединения."""
        return self._ready.wait(timeout=timeout)

    def add_variable(self, name: str, initial_value: Any = 0.0) -> Any:
        """
        Добавить переменную на сервер (блокирующий вызов).
        Возвращает Node для дальнейшего использования в write_value().
        """
        self._ready.wait()
        future = asyncio.run_coroutine_threadsafe(
            self._server.add_variable(name, initial_value), self._loop
        )
        return future.result(timeout=5.0)

    def write_value(self, node_or_name, value: Any) -> None:
        """Обновить значение переменной (не блокирует поток)."""
        if self._loop is None or self._server is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._server.write_value(node_or_name, value), self._loop
        )

    def read_value(self, node_or_name) -> Any:
        """Прочитать текущее значение переменной (блокирующий вызов)."""
        self._ready.wait()
        future = asyncio.run_coroutine_threadsafe(
            self._server.read_value(node_or_name), self._loop
        )
        return future.result(timeout=5.0)

    @property
    def is_running(self) -> bool:
        return self._server.is_running if self._server else False
