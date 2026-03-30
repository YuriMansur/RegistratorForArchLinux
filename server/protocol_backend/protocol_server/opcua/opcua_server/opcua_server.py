"""
AsyncOpcUaServer — OPC UA сервер на базе asyncua.

Позволяет:
  - Запустить OPC UA сервер на заданном endpoint
  - Зарегистрировать namespace и добавить переменные (узлы)
  - Обновлять значения переменных из внешнего кода
  - Получать колбэки при подключении/отключении клиентов

Использование:
    server = AsyncOpcUaServer(endpoint="opc.tcp://0.0.0.0:4841", namespace="urn:registrator")
    await server.start()
    node = await server.add_variable("MyVar", 0.0)
    await server.write_value(node, 42.0)
    await server.stop()
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from asyncua import Server, ua
from asyncua.server.history import HistoryManager

log = logging.getLogger(__name__)


class SessionHandler:
    """Отслеживает подключение и отключение OPC UA клиентов."""

    def __init__(
        self,
        on_connect: Optional[Callable[[str], None]] = None,
        on_disconnect: Optional[Callable[[str], None]] = None,
    ):
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect

    async def activate_session(self, session, context):
        addr = str(getattr(session, "peer_name", "unknown"))
        log.info("OPC UA client connected: %s", addr)
        if self._on_connect:
            try:
                self._on_connect(addr)
            except Exception as e:
                log.error("on_connect callback error: %s", e)

    async def close_session(self, session, delete_subscriptions):
        addr = str(getattr(session, "peer_name", "unknown"))
        log.info("OPC UA client disconnected: %s", addr)
        if self._on_disconnect:
            try:
                self._on_disconnect(addr)
            except Exception as e:
                log.error("on_disconnect callback error: %s", e)


class AsyncOpcUaServer:
    """
    Async OPC UA сервер.

    Атрибуты-колбэки (устанавливаются снаружи):
        on_started     — вызывается когда сервер готов принимать соединения
        on_stopped     — вызывается после остановки сервера
        on_client_connected    — (addr: str)
        on_client_disconnected — (addr: str)
    """

    on_started:              Optional[Callable[[], None]]    = None
    on_stopped:              Optional[Callable[[], None]]    = None
    on_client_connected:     Optional[Callable[[str], None]] = None
    on_client_disconnected:  Optional[Callable[[str], None]] = None

    def __init__(
        self,
        endpoint: str = "opc.tcp://0.0.0.0:4841",
        namespace: str = "urn:registrator:server",
        server_name: str = "Registrator OPC UA Server",
    ):
        self.endpoint   = endpoint
        self.namespace  = namespace
        self.server_name = server_name

        self._server: Optional[Server] = None
        self._ns_idx: int = 0
        self._nodes: Dict[str, Any] = {}   # name → Node object
        self._running = False

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Инициализировать и запустить OPC UA сервер."""
        self._server = Server()
        await self._server.init()

        self._server.set_endpoint(self.endpoint)
        self._server.set_server_name(self.server_name)

        # Разрешаем анонимный доступ
        self._server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

        # Регистрируем namespace
        self._ns_idx = await self._server.register_namespace(self.namespace)
        log.info("Namespace registered: idx=%d  uri=%s", self._ns_idx, self.namespace)

        # Вешаем обработчик сессий
        handler = SessionHandler(
            on_connect=self.on_client_connected,
            on_disconnect=self.on_client_disconnected,
        )
        self._server.subscribe_server_callback(
            ua.ServerDiagnosticsSummaryDataType, handler
        )

        await self._server.start()
        self._running = True
        log.info("OPC UA Server started at %s", self.endpoint)

        if self.on_started:
            try:
                self.on_started()
            except Exception as e:
                log.error("on_started callback error: %s", e)

    async def stop(self) -> None:
        """Остановить OPC UA сервер."""
        if self._server and self._running:
            await self._server.stop()
            self._running = False
            log.info("OPC UA Server stopped")
            if self.on_stopped:
                try:
                    self.on_stopped()
                except Exception as e:
                    log.error("on_stopped callback error: %s", e)

    # ── Управление узлами ─────────────────────────────────────────────────────

    async def add_variable(self, name: str, initial_value: Any = 0.0) -> Any:
        """
        Добавить переменную в корневой объект сервера.
        Возвращает Node — используй для write_value().
        """
        if self._server is None:
            raise RuntimeError("Server not started")
        objects = self._server.get_objects_node()
        node = await objects.add_variable(self._ns_idx, name, initial_value)
        await node.set_writable()
        self._nodes[name] = node
        log.debug("Variable added: %s = %r", name, initial_value)
        return node

    async def write_value(self, node_or_name, value: Any) -> None:
        """
        Обновить значение узла.
        node_or_name — либо Node (из add_variable), либо имя переменной (str).
        """
        if isinstance(node_or_name, str):
            node = self._nodes.get(node_or_name)
            if node is None:
                log.warning("write_value: unknown variable '%s'", node_or_name)
                return
        else:
            node = node_or_name

        await node.write_value(value)

    async def read_value(self, node_or_name) -> Any:
        """Прочитать текущее значение узла."""
        if isinstance(node_or_name, str):
            node = self._nodes.get(node_or_name)
            if node is None:
                log.warning("read_value: unknown variable '%s'", node_or_name)
                return None
        else:
            node = node_or_name
        return await node.read_value()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def ns_idx(self) -> int:
        return self._ns_idx
