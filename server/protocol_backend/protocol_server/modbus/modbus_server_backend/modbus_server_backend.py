"""
ModbusServerBackend — прослойка между ServerManager и ModbusTcpServerThread.

Отвечает за:
  - Запуск / остановку ModbusTcpServerThread
  - Пробрасывание колбэков (on_started, on_stopped)
  - Единый API для работы с регистрами
"""

import logging
from typing import Callable, List, Optional

from protocol_backend.protocol_server.modbus.modbus_server_thread.modbus_server_thread import ModbusTcpServerThread

log = logging.getLogger(__name__)


class ModbusServerBackend:
    """
    Управляет одним Modbus TCP сервером.

    Колбэки:
        on_started  — сервер слушает порт
        on_stopped  — сервер остановлен
    """

    on_started: Optional[Callable[[], None]] = None
    on_stopped: Optional[Callable[[], None]] = None

    def __init__(
        self,
        host:    str = "0.0.0.0",
        port:    int = 502,
        unit_id: int = 1,
    ):
        self._thread = ModbusTcpServerThread(host=host, port=port, unit_id=unit_id)

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread.on_started = self.on_started
        self._thread.on_stopped = self.on_stopped
        self._thread.start()

    def stop(self) -> None:
        self._thread.stop()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        return self._thread.wait_ready(timeout)

    # ── Holding Registers ─────────────────────────────────────────────────────

    def set_holding(self, address: int, value: int) -> None:
        self._thread.set_holding_register(address, value)

    def get_holding(self, address: int) -> int:
        return self._thread.get_holding_register(address)

    def set_holdings(self, address: int, values: List[int]) -> None:
        self._thread.set_holding_registers(address, values)

    def get_holdings(self, address: int, count: int) -> List[int]:
        return self._thread.get_holding_registers(address, count)

    # ── Input Registers ───────────────────────────────────────────────────────

    def set_input(self, address: int, value: int) -> None:
        self._thread.set_input_register(address, value)

    def get_input(self, address: int) -> int:
        return self._thread.get_input_register(address)

    def set_inputs(self, address: int, values: List[int]) -> None:
        self._thread.set_input_registers(address, values)

    # ── Coils ─────────────────────────────────────────────────────────────────

    def set_coil(self, address: int, value: bool) -> None:
        self._thread.set_coil(address, value)

    def get_coil(self, address: int) -> bool:
        return self._thread.get_coil(address)

    def set_coils(self, address: int, values: List[bool]) -> None:
        self._thread.set_coils(address, values)

    # ── Discrete Inputs ───────────────────────────────────────────────────────

    def set_discrete(self, address: int, value: bool) -> None:
        self._thread.set_discrete_input(address, value)

    def get_discrete(self, address: int) -> bool:
        return self._thread.get_discrete_input(address)

    @property
    def is_running(self) -> bool:
        return self._thread.is_running
