"""
ModbusTcpServerThread — threading.Thread обёртка для AsyncModbusTcpServer.

Запускает asyncio event loop в отдельном потоке.
Все операции с регистрами thread-safe — datastore pymodbus потокобезопасен.

Пример:
    thread = ModbusTcpServerThread(host="0.0.0.0", port=502)
    thread.on_started = lambda: print("Modbus server ready")
    thread.start()
    thread.wait_ready()

    thread.set_holding_register(0, 1234)
    val = thread.get_holding_register(0)
    thread.stop()
"""

import asyncio
import logging
import threading
from typing import Callable, List, Optional

from protocol_backend.protocol_server.modbus.modbus_server.modbus_server import AsyncModbusTcpServer

log = logging.getLogger(__name__)


class ModbusTcpServerThread(threading.Thread):
    """
    threading.Thread обёртка для AsyncModbusTcpServer.

    Колбэки (устанавливаются до start()):
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
        **kwargs,
    ):
        super().__init__(daemon=True, name="modbus-server", **kwargs)
        self.host    = host
        self.port    = port
        self.unit_id = unit_id

        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[AsyncModbusTcpServer]      = None
        self._ready   = threading.Event()
        self._stop_event: Optional[asyncio.Event]         = None

    # ── Thread entry ──────────────────────────────────────────────────────────

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception:
            log.exception("ModbusTcpServerThread error")
        finally:
            self._loop.close()

    async def _main(self) -> None:
        self._stop_event = asyncio.Event()
        self._server = AsyncModbusTcpServer(
            host=self.host,
            port=self.port,
            unit_id=self.unit_id,
        )
        self._server.on_started = self._on_started
        self._server.on_stopped = self.on_stopped

        await self._server.start()
        self._ready.set()
        await self._stop_event.wait()
        await self._server.stop()

    def _on_started(self) -> None:
        if self.on_started:
            try:
                self.on_started()
            except Exception as e:
                log.error("on_started callback error: %s", e)

    # ── Управление потоком ────────────────────────────────────────────────────

    def stop(self) -> None:
        """Остановить сервер и поток."""
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self.join(timeout=5.0)

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Подождать пока сервер не будет готов."""
        return self._ready.wait(timeout=timeout)

    # ── Holding Registers ────────────────────────────────────────────────────

    def set_holding_register(self, address: int, value: int) -> None:
        self._ready.wait()
        self._server.set_holding_register(address, value)

    def get_holding_register(self, address: int) -> int:
        self._ready.wait()
        return self._server.get_holding_register(address)

    def set_holding_registers(self, address: int, values: List[int]) -> None:
        self._ready.wait()
        self._server.set_holding_registers(address, values)

    def get_holding_registers(self, address: int, count: int) -> List[int]:
        self._ready.wait()
        return self._server.get_holding_registers(address, count)

    # ── Input Registers ───────────────────────────────────────────────────────

    def set_input_register(self, address: int, value: int) -> None:
        self._ready.wait()
        self._server.set_input_register(address, value)

    def get_input_register(self, address: int) -> int:
        self._ready.wait()
        return self._server.get_input_register(address)

    def set_input_registers(self, address: int, values: List[int]) -> None:
        self._ready.wait()
        self._server.set_input_registers(address, values)

    # ── Coils ─────────────────────────────────────────────────────────────────

    def set_coil(self, address: int, value: bool) -> None:
        self._ready.wait()
        self._server.set_coil(address, value)

    def get_coil(self, address: int) -> bool:
        self._ready.wait()
        return self._server.get_coil(address)

    def set_coils(self, address: int, values: List[bool]) -> None:
        self._ready.wait()
        self._server.set_coils(address, values)

    # ── Discrete Inputs ───────────────────────────────────────────────────────

    def set_discrete_input(self, address: int, value: bool) -> None:
        self._ready.wait()
        self._server.set_discrete_input(address, value)

    def get_discrete_input(self, address: int) -> bool:
        self._ready.wait()
        return self._server.get_discrete_input(address)

    @property
    def is_running(self) -> bool:
        return self._server.is_running if self._server else False
