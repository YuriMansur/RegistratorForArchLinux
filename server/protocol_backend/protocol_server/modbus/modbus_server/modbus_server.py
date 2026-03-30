"""
AsyncModbusTcpServer — Modbus TCP сервер на базе pymodbus.

Регистры (unit_id=1 по умолчанию):
  - Holding Registers  (FC 3/6/16) — read/write, 16-bit int
  - Input Registers    (FC 4)      — read only, 16-bit int
  - Coils              (FC 1/5/15) — read/write, 1-bit bool
  - Discrete Inputs    (FC 2)      — read only, 1-bit bool

Использование:
    server = AsyncModbusTcpServer(host="0.0.0.0", port=502)
    await server.start()
    server.set_holding_register(address=0, value=1234)
    value = server.get_holding_register(address=0)
    await server.stop()
"""

import asyncio
import logging
from typing import Callable, List, Optional

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

log = logging.getLogger(__name__)

_BLOCK_SIZE = 1000   # количество регистров/катушек на блок


class AsyncModbusTcpServer:
    """
    Async Modbus TCP сервер.

    Колбэки (устанавливаются снаружи):
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
        self.host    = host
        self.port    = port
        self.unit_id = unit_id

        # Инициализируем хранилища регистров нулями
        self._slave = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * _BLOCK_SIZE),   # Discrete Inputs
            co=ModbusSequentialDataBlock(0, [0] * _BLOCK_SIZE),   # Coils
            hr=ModbusSequentialDataBlock(0, [0] * _BLOCK_SIZE),   # Holding Registers
            ir=ModbusSequentialDataBlock(0, [0] * _BLOCK_SIZE),   # Input Registers
        )
        self._context = ModbusServerContext(
            slaves={unit_id: self._slave}, single=False
        )

        self._server_task: Optional[asyncio.Task] = None
        self._stop_event:  Optional[asyncio.Event] = None
        self._running = False

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Запустить Modbus TCP сервер (не блокирует — задача в фоне)."""
        self._stop_event = asyncio.Event()
        self._server_task = asyncio.get_event_loop().create_task(self._run())

        # Ждём пока сервер поднимется
        await asyncio.sleep(0.2)
        self._running = True
        log.info("Modbus TCP Server started at %s:%d", self.host, self.port)
        if self.on_started:
            try:
                self.on_started()
            except Exception as e:
                log.error("on_started callback error: %s", e)

    async def _run(self) -> None:
        try:
            await StartAsyncTcpServer(
                context=self._context,
                address=(self.host, self.port),
            )
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Modbus TCP Server error")

    async def stop(self) -> None:
        """Остановить сервер."""
        if self._server_task and not self._server_task.done():
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        self._running = False
        log.info("Modbus TCP Server stopped")
        if self.on_stopped:
            try:
                self.on_stopped()
            except Exception as e:
                log.error("on_stopped callback error: %s", e)

    # ── Holding Registers (FC 3 / 6 / 16) ────────────────────────────────────

    def set_holding_register(self, address: int, value: int) -> None:
        """Записать значение в Holding Register (0–65535)."""
        self._slave.setValues(3, address, [int(value) & 0xFFFF])

    def get_holding_register(self, address: int) -> int:
        """Прочитать Holding Register."""
        return self._slave.getValues(3, address, count=1)[0]

    def set_holding_registers(self, address: int, values: List[int]) -> None:
        """Записать несколько Holding Registers подряд."""
        self._slave.setValues(3, address, [v & 0xFFFF for v in values])

    def get_holding_registers(self, address: int, count: int) -> List[int]:
        """Прочитать несколько Holding Registers."""
        return self._slave.getValues(3, address, count=count)

    # ── Input Registers (FC 4, read-only для клиента) ─────────────────────────

    def set_input_register(self, address: int, value: int) -> None:
        """Обновить Input Register (сервер пишет, клиент только читает)."""
        self._slave.setValues(4, address, [int(value) & 0xFFFF])

    def get_input_register(self, address: int) -> int:
        return self._slave.getValues(4, address, count=1)[0]

    def set_input_registers(self, address: int, values: List[int]) -> None:
        self._slave.setValues(4, address, [v & 0xFFFF for v in values])

    # ── Coils (FC 1 / 5 / 15) ─────────────────────────────────────────────────

    def set_coil(self, address: int, value: bool) -> None:
        """Записать Coil (0 или 1)."""
        self._slave.setValues(1, address, [bool(value)])

    def get_coil(self, address: int) -> bool:
        return bool(self._slave.getValues(1, address, count=1)[0])

    def set_coils(self, address: int, values: List[bool]) -> None:
        self._slave.setValues(1, address, [bool(v) for v in values])

    # ── Discrete Inputs (FC 2, read-only для клиента) ─────────────────────────

    def set_discrete_input(self, address: int, value: bool) -> None:
        """Обновить Discrete Input (сервер пишет, клиент только читает)."""
        self._slave.setValues(2, address, [bool(value)])

    def get_discrete_input(self, address: int) -> bool:
        return bool(self._slave.getValues(2, address, count=1)[0])

    # ── Утилиты ───────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running
