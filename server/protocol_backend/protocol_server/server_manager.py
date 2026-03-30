"""
ServerManager — поднимает серверы протоколов и регистрирует теги.

Все конкретные сервера и теги описаны прямо здесь.
После start() теги создаются автоматически и доступны по имени.

Архитектура:
    ServerManager
      ├── OpcUaServerBackend  →  OpcUaServerThread  →  AsyncOpcUaServer
      └── ModbusServerBackend →  ModbusTcpServerThread → AsyncModbusTcpServer
"""

import logging
import threading
from typing import Any, Dict

from protocol_backend.protocol_server.opcua.opcua_server_backend.opcua_server_backend import OpcUaServerBackend
from protocol_backend.protocol_server.modbus.modbus_server_backend.modbus_server_backend import ModbusServerBackend

log = logging.getLogger(__name__)


# ── OPC UA сервер ──────────────────────────────────────────────────────────────

_OPC_SERVER = {
    "endpoint":    "opc.tcp://0.0.0.0:4841",
    "namespace":   "urn:registrator:server",
    "server_name": "Registrator OPC UA Server",
}

# Теги OPC UA: имя переменной → начальное значение
_OPC_TAGS: Dict[str, Any] = {
    "Temperature":  0.0,
    "Pressure":     0.0,
    "Status":       False,
}


# ── Modbus TCP сервер ──────────────────────────────────────────────────────────

_MODBUS_SERVER = {
    "host":    "0.0.0.0",
    "port":    502,
    "unit_id": 1,
}

# Теги Modbus: имя → (тип регистра, адрес, начальное значение)
# Тип: "holding" | "input" | "coil" | "discrete"
_MODBUS_TAGS: Dict[str, tuple] = {
    "Temperature":  ("holding",  0,  0),
    "Pressure":     ("holding",  1,  0),
    "Status":       ("coil",     0,  False),
    "Alarm":        ("discrete", 0,  False),
}


# ── ServerManager ──────────────────────────────────────────────────────────────

class ServerManager:

    def __init__(self):
        self._opc    = OpcUaServerBackend(**_OPC_SERVER)
        self._modbus = ModbusServerBackend(**_MODBUS_SERVER)

        # Node-объекты OPC UA после регистрации тегов
        self._opc_nodes: Dict[str, Any] = {}

        self._wire_callbacks()

    # ── Колбэки ────────────────────────────────────────────────────────────────

    def _wire_callbacks(self) -> None:
        self._opc.on_started             = lambda: log.info("OPC UA server started")
        self._opc.on_stopped             = lambda: log.info("OPC UA server stopped")
        self._opc.on_client_connected    = lambda addr: log.info("OPC UA client connected: %s", addr)
        self._opc.on_client_disconnected = lambda addr: log.info("OPC UA client disconnected: %s", addr)

        self._modbus.on_started = lambda: log.info("Modbus TCP server started")
        self._modbus.on_stopped = lambda: log.info("Modbus TCP server stopped")

    # ── Запуск / остановка ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Запустить серверы и зарегистрировать теги."""
        self._opc.start()
        self._modbus.start()

        # Теги OPC UA регистрируем в отдельном потоке — ждём готовности сервера
        threading.Thread(target=self._register_opc_tags, daemon=True).start()

        # Теги Modbus инициализируем сразу — datastore готов до start()
        self._register_modbus_tags()

    def stop(self) -> None:
        """Остановить все серверы."""
        self._opc.stop()
        self._modbus.stop()

    # ── Регистрация тегов ──────────────────────────────────────────────────────

    def _register_opc_tags(self) -> None:
        """Дождаться старта OPC UA сервера и добавить переменные."""
        if not self._opc.wait_ready(timeout=15.0):
            log.error("OPC UA server not ready — tags not registered")
            return
        for name, initial in _OPC_TAGS.items():
            node = self._opc.add_variable(name, initial)
            self._opc_nodes[name] = node
            log.info("OPC UA tag registered: %s = %r", name, initial)

    def _register_modbus_tags(self) -> None:
        """Записать начальные значения Modbus регистров."""
        _writers = {
            "holding":  self._modbus.set_holding,
            "input":    self._modbus.set_input,
            "coil":     self._modbus.set_coil,
            "discrete": self._modbus.set_discrete,
        }
        for name, (reg_type, address, initial) in _MODBUS_TAGS.items():
            writer = _writers.get(reg_type)
            if writer:
                writer(address, initial)
                log.info("Modbus tag registered: %s  [%s:%d] = %r", name, reg_type, address, initial)

    # ── OPC UA: запись / чтение по имени тега ─────────────────────────────────

    def opc_write(self, tag: str, value: Any) -> None:
        """Записать значение OPC UA тега по имени."""
        node = self._opc_nodes.get(tag)
        if node is None:
            log.error("opc_write: unknown tag '%s'", tag)
            return
        self._opc.write(node, value)

    def opc_read(self, tag: str) -> Any:
        """Прочитать значение OPC UA тега по имени."""
        node = self._opc_nodes.get(tag)
        if node is None:
            log.error("opc_read: unknown tag '%s'", tag)
            return None
        return self._opc.read(node)

    # ── Modbus: запись / чтение по имени тега ─────────────────────────────────

    def modbus_write(self, tag: str, value: Any) -> None:
        """Записать значение Modbus тега по имени."""
        entry = _MODBUS_TAGS.get(tag)
        if entry is None:
            log.error("modbus_write: unknown tag '%s'", tag)
            return
        reg_type, address, _ = entry
        _writers = {
            "holding":  self._modbus.set_holding,
            "input":    self._modbus.set_input,
            "coil":     self._modbus.set_coil,
            "discrete": self._modbus.set_discrete,
        }
        writer = _writers.get(reg_type)
        if writer:
            writer(address, value)

    def modbus_read(self, tag: str) -> Any:
        """Прочитать значение Modbus тега по имени."""
        entry = _MODBUS_TAGS.get(tag)
        if entry is None:
            log.error("modbus_read: unknown tag '%s'", tag)
            return None
        reg_type, address, _ = entry
        _readers = {
            "holding":  self._modbus.get_holding,
            "input":    self._modbus.get_input,
            "coil":     self._modbus.get_coil,
            "discrete": self._modbus.get_discrete,
        }
        reader = _readers.get(reg_type)
        return reader(address) if reader else None

    # ── Статус ─────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, bool]:
        return {
            "opcua":  self._opc.is_running,
            "modbus": self._modbus.is_running,
        }
