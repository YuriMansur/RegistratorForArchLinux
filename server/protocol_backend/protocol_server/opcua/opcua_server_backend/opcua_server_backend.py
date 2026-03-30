"""
OpcUaServerBackend — прослойка между ServerManager и OpcUaServerThread.

Отвечает за:
  - Запуск / остановку OpcUaServerThread
  - Пробрасывание колбэков (on_started, on_client_connected, ...)
  - Простой API для работы с переменными (add_variable, write, read)
"""

import logging
from typing import Any, Callable, Dict, Optional

from protocol_backend.protocol_server.opcua.opcua_server_thread.opcua_server_thread import OpcUaServerThread

log = logging.getLogger(__name__)


class OpcUaServerBackend:
    """
    Управляет одним OPC UA сервером.

    Колбэки:
        on_started              — сервер готов
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
        endpoint:    str = "opc.tcp://0.0.0.0:4841",
        namespace:   str = "urn:registrator:server",
        server_name: str = "Registrator OPC UA Server",
    ):
        self._thread = OpcUaServerThread(
            endpoint=endpoint,
            namespace=namespace,
            server_name=server_name,
        )
        self._nodes: Dict[str, Any] = {}   # name → Node

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread.on_started             = self.on_started
        self._thread.on_stopped             = self.on_stopped
        self._thread.on_client_connected    = self.on_client_connected
        self._thread.on_client_disconnected = self.on_client_disconnected
        self._thread.start()

    def stop(self) -> None:
        self._thread.stop()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._thread.wait_ready(timeout)

    # ── Переменные ────────────────────────────────────────────────────────────

    def add_variable(self, name: str, initial_value: Any = 0.0) -> Any:
        """Добавить переменную. Возвращает Node."""
        node = self._thread.add_variable(name, initial_value)
        self._nodes[name] = node
        return node

    def write(self, name_or_node: Any, value: Any) -> None:
        """Записать значение по имени или Node."""
        if isinstance(name_or_node, str):
            node = self._nodes.get(name_or_node)
            if node is None:
                log.error("OpcUaServerBackend: unknown variable '%s'", name_or_node)
                return
            self._thread.write_value(node, value)
        else:
            self._thread.write_value(name_or_node, value)

    def read(self, name_or_node: Any) -> Any:
        """Прочитать значение по имени или Node."""
        if isinstance(name_or_node, str):
            node = self._nodes.get(name_or_node)
            if node is None:
                log.error("OpcUaServerBackend: unknown variable '%s'", name_or_node)
                return None
            return self._thread.read_value(node)
        return self._thread.read_value(name_or_node)

    @property
    def is_running(self) -> bool:
        return self._thread.is_running
