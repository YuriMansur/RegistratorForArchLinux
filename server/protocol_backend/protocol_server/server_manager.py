"""
ServerManager — поднимает OPC UA сервер с тестовыми тегами.
"""

import logging
import math
import threading
import time
from typing import Any, Dict

from protocol_backend.protocol_server.opcua.opcua_server_backend.opcua_server_backend import OpcUaServerBackend

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
    "TestSine":     0.0,   # синусоида 0..100
    "TestRamp":     0.0,   # пила 0..100
}


# ── ServerManager ──────────────────────────────────────────────────────────────

class ServerManager:

    def __init__(self):
        self._opc = OpcUaServerBackend(**_OPC_SERVER)
        self._opc_nodes: Dict[str, Any] = {}
        self._wire_callbacks()

    def _wire_callbacks(self) -> None:
        self._opc.on_started             = lambda: log.info("OPC UA server started")
        self._opc.on_stopped             = lambda: log.info("OPC UA server stopped")
        self._opc.on_client_connected    = lambda addr: log.info("OPC UA client connected: %s", addr)
        self._opc.on_client_disconnected = lambda addr: log.info("OPC UA client disconnected: %s", addr)

    def start(self) -> None:
        self._opc.start()
        threading.Thread(target=self._register_opc_tags, daemon=True).start()

    def stop(self) -> None:
        self._opc.stop()

    def _register_opc_tags(self) -> None:
        if not self._opc.wait_ready(timeout=15.0):
            log.error("OPC UA server not ready — tags not registered")
            return
        for name, initial in _OPC_TAGS.items():
            node = self._opc.add_variable(name, initial)
            self._opc_nodes[name] = node
            log.info("OPC UA tag registered: %s = %r", name, initial)
        threading.Thread(target=self._update_test_tags, daemon=True).start()

    def _update_test_tags(self) -> None:
        """Постоянно обновляет TestSine и TestRamp с интервалом 1с."""
        t = 0.0
        ramp = 0.0
        while True:
            self.opc_write("TestSine", round(50.0 + 50.0 * math.sin(t), 3))
            self.opc_write("TestRamp", round(ramp % 100.0, 3))
            t    += 0.1
            ramp += 1.0
            time.sleep(1.0)

    def opc_write(self, tag: str, value: Any) -> None:
        node = self._opc_nodes.get(tag)
        if node is None:
            return
        self._opc.write(node, value)

    def opc_read(self, tag: str) -> Any:
        node = self._opc_nodes.get(tag)
        if node is None:
            return None
        return self._opc.read(node)

    def status(self) -> Dict[str, bool]:
        return {"opcua": self._opc.is_running}
