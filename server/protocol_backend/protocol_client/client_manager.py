import re
import logging
import threading
from datetime import datetime, timezone
from protocol_backend.protocol_client.opcua.opcua_backend.opcua_backend import OpcUaBackend
from protocol_backend.protocol_client.opcua_tags import Dev_192_168_10_10_OPC_Tags as Tags
from db import tag_writer
from db import session_exporter
from db import test_manager


# ── Конфигурация серверов ─────────────────────────────────────────────────────
_SERVERS = [
    {
        "name"              : "PLC1",
        "endpoint"          : "opc.tcp://192.168.10.10:4840",
        "auto_reconnect"    : True,
        "reconnect_interval": 5,
        "subscribe"         : [Tags.inProcess, Tags.End],
        "polls"             : [
            {"name": "arrays", "nodes": [Tags.ForUra], "interval": 1.0, "sequential": True},
        ],
    },
]

log = logging.getLogger(__name__)

# Обратный маппинг: node_id → имя переменной из класса тегов
_NODE_NAMES: dict[str, str] = {
    v: k for k, v in vars(Tags).items() if not k.startswith("_")
}


_CONTROL_TAGS = {Tags.inProcess, Tags.End}


class ServerManager:
    """Управляет OPC UA серверами. Пишет данные тегов в SQLite через tag_writer."""

    def __init__(self):
        self._backend = OpcUaBackend()
        self._timers: dict[str, threading.Timer] = {}
        self._config: dict[str, dict] = {}
        self._recording: bool = False
        self._session_start: datetime | None = None
        self._current_test_id: int | None = None
        self._setup()

    # ── Публичный API ─────────────────────────────────────────────────────────

    def start(self):
        """Подключиться ко всем серверам."""
        for name in self._config:
            self._backend.connect_server(name)

    def stop(self):
        """Отключиться от всех серверов."""
        logging.getLogger("asyncua").setLevel(logging.CRITICAL)
        for timer in self._timers.values():
            timer.cancel()
        self._backend.stop_all()

    def write_tag(self, srv: str, node_id: str, value):
        self._backend.write_node(srv, node_id, value)

    # ── Инициализация ─────────────────────────────────────────────────────────

    def _setup(self):
        for cfg in _SERVERS:
            name = cfg["name"]
            self._config[name] = cfg
            self._backend.add_server(name, cfg["endpoint"])
        self._wire_callbacks()

    def _wire_callbacks(self):
        b = self._backend
        b.on_connected        = self._on_connected
        b.on_disconnected     = self._on_disconnected
        b.on_data_updated     = self._on_data_received
        b.on_connection_error = lambda srv, err: log.error("OPC error [%s]: %s", srv, err)

    # ── Обработчики событий backend ───────────────────────────────────────────

    def _on_connected(self, srv: str):
        self._cancel_timer(srv)
        log.info("Connected to %s", srv)
        cfg = self._config.get(srv, {})
        subscribe_tags = cfg.get("subscribe", [])
        for node_id in subscribe_tags:
            self._backend.subscribe_tag(srv, node_id)
        if subscribe_tags:
            self._backend.read_multiple_nodes(srv, subscribe_tags)
        for poll in cfg.get("polls", []):
            self._backend.start_polling(
                srv, poll["name"], poll["nodes"],
                poll["interval"], poll.get("sequential", False)
            )
        self._backend.start_watchdog(srv, interval=10.0)

    def _on_disconnected(self, srv: str):
        log.warning("Disconnected from %s", srv)
        cfg = self._config.get(srv, {})
        if cfg.get("auto_reconnect", True):
            interval = cfg.get("reconnect_interval", 5)
            self._schedule_reconnect(srv, interval)

    def _schedule_reconnect(self, name: str, interval: float):
        self._cancel_timer(name)
        t = threading.Timer(interval, self._backend.connect_server, args=[name])
        t.daemon = True
        t.start()
        self._timers[name] = t
        log.info("Reconnecting to %s in %ss...", name, interval)

    def _cancel_timer(self, name: str):
        t = self._timers.pop(name, None)
        if t:
            t.cancel()

    # ── Маршрутизация входящих данных ─────────────────────────────────────────

    def _on_data_received(self, srv: str, nid: str, val):
        """Единая точка входа для всех данных от PLC → пишем в SQLite."""
        nid = self._normalize_nid(nid)
        tag_name = _NODE_NAMES.get(nid, nid)

        # Управляющие теги — обновляем значение, но не пишем в историю
        if nid in _CONTROL_TAGS:
            tag_writer.write_tag(tag_id=nid, value=val, tag_name=tag_name, record_history=False)
            self._handle_control(nid, val)
            return

        # Обычные теги — пишем в историю только во время сессии
        tag_writer.write_tag(
            tag_id=nid, value=val, tag_name=tag_name,
            record_history=self._recording,
            test_id=self._current_test_id,
        )

    def _handle_control(self, nid: str, val):
        if nid == Tags.inProcess and bool(val) and not self._recording:
            self._recording = True
            self._session_start = datetime.now(timezone.utc)
            self._current_test_id = test_manager.start_test()
            log.info("Session started (test_id=%s)", self._current_test_id)

        elif nid == Tags.End and bool(val) and self._recording:
            self._recording = False
            session_end = datetime.now(timezone.utc)
            test_manager.end_test(self._current_test_id)
            log.info("Session ended (test_id=%s), exporting...", self._current_test_id)
            threading.Thread(
                target=session_exporter.export_session,
                args=(self._session_start, session_end, self._current_test_id),
                daemon=True,
            ).start()
            self._session_start = None
            self._current_test_id = None

    @staticmethod
    def _normalize_nid(nid: str) -> str:
        """Привести NodeId к формату ns=X;s=... если пришёл объект asyncua NodeId."""
        if not nid.startswith("NodeId("):
            return nid
        m_ns = re.search(r"NamespaceIndex=(\d+)", nid)
        m_id = re.search(r"Identifier='([^']+)'", nid)
        if m_ns and m_id:
            return f"ns={m_ns.group(1)};s={m_id.group(1)}"
        return nid
