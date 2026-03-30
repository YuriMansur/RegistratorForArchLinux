"""
ModbusBackend - API для программного управления множественными Modbus PLC

═══════════════════════════════════════════════════════════════════════════════
НАЗНАЧЕНИЕ:
═══════════════════════════════════════════════════════════════════════════════
Backend класс для управления PLC БЕЗ GUI. Предоставляет программный API для:
- Добавления/удаления устройств
- Подключения/отключения
- Выполнения команд (read/write)
- Добавления циклических опросов (polls)
- Получения данных в реальном времени

ОТЛИЧИЕ ОТ ModbusDebugger:
=========================
ModbusDebugger - GUI приложение (визуальная отладка)
ModbusBackend  - Программный API (интеграция в приложения)

АРХИТЕКТУРА:
============
    ┌──────────────────────────────────────────────┐
    │         User Application (ваш код)           │
    │                                              │
    │  backend = ModbusBackend()                  │
    │  backend.add_device("PLC1", "192.168.1.1")  │
    │  backend.connect_device("PLC1")             │
    │  data = backend.get_latest_data("PLC1")     │
    └───────────────┬──────────────────────────────┘
                    │
                    ▼
    ┌──────────────────────────────────────────────┐
    │          ModbusBackend (этот класс)          │
    │                                              │
    │  • Управление словарем PLC                  │
    │  • Thread-safe API                          │
    │  • Callbacks для событий                    │
    └───────────────┬──────────────────────────────┘
                    │
            ┌───────┴────────┐
            ▼                ▼
    ┌──────────────┐  ┌──────────────┐
    │PLCWorkerThread│ │PLCWorkerThread│
    │    (PLC1)    │  │    (PLC2)    │
    │              │  │              │
    │  asyncio     │  │  asyncio     │
    │  event loop  │  │  event loop  │
    └──────────────┘  └──────────────┘

ПРИМЕР ИСПОЛЬЗОВАНИЯ:
====================

from modbus_backend import ModbusBackend

# Создаем backend
backend = ModbusBackend()

# Регистрируем callback для событий (опционально)
backend.on_connected = lambda plc_id: print(f"{plc_id} connected!")
backend.on_data_updated = lambda plc_id, data: print(f"{plc_id}: {data}")

# Добавляем устройства программно
backend.add_device("PLC1", host="192.168.1.1", port=502, device_id=1)
backend.add_device("PLC2", host="192.168.1.2", port=502, device_id=1)

# Подключаемся
backend.connect_device("PLC1")
backend.connect_device("PLC2")

# Добавляем циклический опрос
backend.add_poll("PLC1", {
    "name": "sensors",
    "type": "holding",
    "address": 0,
    "count": 10,
    "interval": 1.0
})

# Выполняем команду чтения
result = backend.execute_command_sync("PLC1", ("read", "holding", 0, 10))
print(f"Data: {result}")

# Получаем последние данные от polls
data = backend.get_latest_data("PLC1")
print(f"Latest polls data: {data}")

# Отключаемся
backend.disconnect_device("PLC1")
backend.stop_all()  # Останавливаем все при завершении

ИНТЕГРАЦИЯ С GUI:
================
Backend может использоваться совместно с GUI:
- GUI вызывает методы backend для управления
- GUI подписывается на callbacks для обновлений
- GUI отображает данные от backend

backend = ModbusBackend()
gui = ModbusDebugger(backend)  # GUI получает backend в конструктор
gui.show()

THREAD-SAFETY:
=============
Все публичные методы thread-safe и могут вызываться из любого потока.
"""

from typing import Optional, Dict, Callable, Any, Union, List
from PyQt6.QtCore import QObject, pyqtSignal
import asyncio
import threading
from concurrent.futures import Future

from protocol_backend.protocol_client.modbus.tcp.modbus_worker_thread import PLCWorkerThread
from protocol_backend.protocol_client.modbus.tcp.regs_convert import ConvertProtocolData


class ModbusBackend(QObject):
    """
    Backend для программного управления множественными Modbus PLC

    Предоставляет API для добавления устройств, подключения, выполнения команд
    и получения данных БЕЗ GUI.

    CALLBACKS:
    ==========
    Можно зарегистрировать callback функции для обработки событий:
    - on_connected(plc_id: str) - успешное подключение
    - on_disconnected(plc_id: str) - отключение
    - on_connection_error(plc_id: str, error: str) - ошибка подключения
    - on_command_completed(plc_id: str, result) - результат команды
    - on_command_error(plc_id: str, error: str) - ошибка команды
    - on_data_updated(plc_id: str, poll_name: str, data: dict) - обновление данных

    СИГНАЛЫ (для интеграции с Qt GUI):
    ==================================
    Если вы используете Qt GUI, backend также эмитит сигналы:
    - device_added - добавлено устройство
    - device_removed - удалено устройство
    - device_connected - устройство подключено
    - device_disconnected - устройство отключено
    - device_error - ошибка устройства
    """

    # ===== SIGNALS для интеграции с Qt GUI =====
    device_added = pyqtSignal(str)          # (plc_id)
    device_removed = pyqtSignal(str)        # (plc_id)
    device_connected = pyqtSignal(str)      # (plc_id)
    device_disconnected = pyqtSignal(str)   # (plc_id)
    device_error = pyqtSignal(str, str)     # (plc_id, error)
    data_updated = pyqtSignal(str, str, dict)  # (plc_id, poll_name, data)

    def __init__(self):
        """Инициализация backend"""
        super().__init__()

        # ===== ХРАНИЛИЩЕ УСТРОЙСТВ =====
        # Структура: {plc_id: {"thread": PLCWorkerThread, "config": {...}, "connected": bool}}
        self.plcs: Dict[str, dict] = {}

        # ===== CALLBACKS =====
        # Пользователь может установить эти функции для обработки событий
        self.on_connected: Optional[Callable[[str], None]] = None
        self.on_disconnected: Optional[Callable[[str], None]] = None
        self.on_connection_error: Optional[Callable[[str, str], None]] = None
        self.on_command_completed: Optional[Callable[[str, Any], None]] = None
        self.on_command_error: Optional[Callable[[str, str], None]] = None
        self.on_data_updated: Optional[Callable[[str, str, dict], None]] = None

        # ===== PENDING SYNC CALLS =====
        # Один ожидающий Future на PLC для синхронных методов (read_registers и т.д.)
        self._pending_futures: Dict[str, Future] = {}
        self._pending_lock = threading.Lock()

    # ==========================================================================
    # DEVICE MANAGEMENT API
    # ==========================================================================

    def add_device(self, plc_id: str, host: str, port: int = 502, device_id: int = 1) -> bool:
        """
        Добавить устройство в backend (БЕЗ подключения)

        Args:
            plc_id: Уникальный идентификатор PLC
            host: IP адрес устройства
            port: Modbus TCP порт (по умолчанию 502)
            device_id: Modbus slave ID (по умолчанию 1)

        Returns:
            bool: True если устройство добавлено, False если уже существует
        """
        if plc_id in self.plcs:
            return False  # Устройство уже существует

        # Добавляем устройство (thread будет создан при connect)
        self.plcs[plc_id] = {
            "thread": None,
            "connected": False,
            "config": {
                "host": host,
                "port": port,
                "device_id": device_id
            }
        }

        # Эмитим signal
        self.device_added.emit(plc_id)

        return True

    def remove_device(self, plc_id: str, force: bool = False) -> bool:
        """
        Удалить устройство из backend

        Args:
            plc_id: ID устройства для удаления
            force: Принудительное удаление (отключить если подключено)

        Returns:
            bool: True если устройство удалено, False если не найдено или подключено
        """
        if plc_id not in self.plcs:
            return False  # Устройство не найдено

        plc = self.plcs[plc_id]

        # Если устройство подключено и не force - отклоняем
        if plc["connected"] and not force:
            return False

        # Если force и подключено - сначала отключаем (blocking, чтобы thread полностью остановился)
        if plc["connected"] and force:
            self.disconnect_device(plc_id, blocking=True)

        # Удаляем устройство
        del self.plcs[plc_id]

        # Эмитим signal
        self.device_removed.emit(plc_id)

        return True

    def get_devices(self) -> Dict[str, dict]:
        """
        Получить список всех устройств

        Returns:
            dict: Словарь устройств {plc_id: {"connected": bool, "config": {...}}}
        """
        return {
            plc_id: {
                "connected": plc["connected"],
                "config": plc["config"].copy()
            }
            for plc_id, plc in self.plcs.items()
        }

    def is_connected(self, plc_id: str) -> bool:
        """
        Проверить статус подключения устройства

        Args:
            plc_id: ID устройства

        Returns:
            bool: True если подключено, False если нет или устройство не найдено
        """
        plc = self.plcs.get(plc_id)
        if not plc:
            return False
        thread = plc.get("thread")
        if thread:
            return thread.is_connected  # источник истины (учитывает auto-reconnect)
        return plc["connected"]

    # ==========================================================================
    # CONNECTION API
    # ==========================================================================

    def connect_device(self, plc_id: str) -> bool:
        """
        Подключиться к устройству

        Args:
            plc_id: ID устройства для подключения

        Returns:
            bool: True если подключение запущено, False если устройство не найдено
        """
        if plc_id not in self.plcs:
            return False

        plc = self.plcs[plc_id]

        # Проверка на повторное подключение
        if plc["connected"]:
            return True  # Уже подключено

        try:
            config = plc["config"]

            # Создаем PLCWorkerThread
            thread = PLCWorkerThread(
                plc_id, config["host"], config["port"], config["device_id"]
            )

            # Подключаем signals
            thread.loop_ready.connect(lambda: thread.connect_to_plc())
            thread.connected.connect(lambda: self._on_device_connected(plc_id))
            thread.disconnected.connect(lambda: self._on_device_disconnected(plc_id))
            thread.connection_error.connect(lambda err: self._on_device_error(plc_id, err))
            thread.command_completed.connect(lambda res: self._on_command_result(plc_id, res))
            thread.command_error.connect(lambda err: self._on_command_error(plc_id, err))
            thread.data_updated.connect(lambda poll_name, data: self._on_data_updated(plc_id, poll_name, data))

            # Сохраняем thread и запускаем
            plc["thread"] = thread
            thread.start()

            return True

        except Exception as e:
            # Ошибка создания потока
            plc["thread"] = None
            self._on_device_error(plc_id, str(e))
            return False

    def disconnect_device(self, plc_id: str, blocking: bool = False) -> bool:
        """
        Отключиться от устройства

        Args:
            plc_id: ID устройства для отключения
            blocking: Блокирующий режим (ждать завершения)

        Returns:
            bool: True если отключение запущено, False если устройство не найдено
        """
        if plc_id not in self.plcs:
            return False

        plc = self.plcs[plc_id]

        if not plc["connected"] and not plc.get("thread"):
            return True  # Уже отключено

        try:
            if plc.get("thread"):
                # Останавливаем thread (неблокирующий режим по умолчанию)
                plc["thread"].stop(blocking=blocking)

            return True

        except Exception as e:
            # Ошибка отключения
            plc["connected"] = False
            plc["thread"] = None
            return False

    def connect_all(self):
        """Подключиться ко всем добавленным устройствам"""
        for plc_id in self.plcs.keys():
            if not self.is_connected(plc_id):
                self.connect_device(plc_id)

    def disconnect_all(self, blocking: bool = False):
        """Отключиться от всех устройств"""
        for plc_id in list(self.plcs.keys()):
            if self.is_connected(plc_id):
                self.disconnect_device(plc_id, blocking=blocking)

    # ==========================================================================
    # COMMAND API
    # ==========================================================================

    def execute_command(self, plc_id: str, command: tuple):
        """
        Выполнить команду на устройстве (асинхронно)

        Результат придет через callback on_command_completed или on_command_error

        Args:
            plc_id: ID устройства
            command: tuple команды ("read", type, address, count) или
                    ("write", type, address, count, value)
        """
        plc = self.plcs.get(plc_id)
        if not plc or not plc["connected"] or not plc.get("thread"):
            if self.on_command_error:
                self.on_command_error(plc_id, "Device not connected")
            return

        plc["thread"].execute_command(command)

    def execute_command_sync(self, plc_id: str, command: tuple, timeout: float = 5.0) -> Any:
        """
        Выполнить команду синхронно и вернуть результат.

        Args:
            plc_id: ID устройства
            command: tuple команды ("read", type, address, count) или
                    ("write", type, address, count, value)
            timeout: Таймаут ожидания результата (секунды)

        Returns:
            Результат команды или None при ошибке

        Example:
            result = backend.execute_command_sync("PLC1", ("read", "holding", 0, 10))
            print(f"Data: {result}")
        """
        plc = self.plcs.get(plc_id)
        if not plc or not plc.get("thread"):
            return None
        try:
            return self._execute_and_wait(plc_id, command, timeout)
        except Exception:
            return None

    def _execute_and_wait(self, plc_id: str, command: tuple, timeout: float) -> Any:
        """
        Отправить команду и заблокировать поток до получения результата.

        Использует per-PLC Future из self._pending_futures — не затрагивает
        глобальные on_command_completed / on_command_error, поэтому
        параллельные вызовы на разных PLC полностью независимы.

        Raises:
            RuntimeError: Если для этого plc_id уже есть ожидающая операция.
            Exception:    При ошибке команды или по таймауту.
        """
        with self._pending_lock:
            if plc_id in self._pending_futures and not self._pending_futures[plc_id].done():
                raise RuntimeError(f"Another sync command is already pending for '{plc_id}'")
            fut: Future = Future()
            self._pending_futures[plc_id] = fut
        try:
            self.execute_command(plc_id, command)
            return fut.result(timeout=timeout)
        finally:
            with self._pending_lock:
                self._pending_futures.pop(plc_id, None)

    # ==========================================================================
    # POLL API
    # ==========================================================================

    def add_poll(self, plc_id: str, poll_config: dict):
        """
        Добавить циклический опрос на устройство

        Args:
            plc_id: ID устройства
            poll_config: dict с ключами: name, type, address, count, interval
        """
        plc = self.plcs.get(plc_id)
        if not plc or not plc["connected"] or not plc.get("thread"):
            return

        # Добавляем префикс plc_id к имени poll для уникальности
        poll_config_with_prefix = poll_config.copy()
        poll_config_with_prefix["name"] = f"{plc_id}_{poll_config['name']}"

        plc["thread"].add_poll(poll_config_with_prefix)

    def get_latest_data(self, plc_id: str) -> Optional[Dict[str, list]]:
        """
        Получить последние данные от polls устройства

        Args:
            plc_id: ID устройства

        Returns:
            dict: {poll_name: data} или None если устройство не подключено
        """
        plc = self.plcs.get(plc_id)
        if not plc or not plc.get("thread"):
            return None

        return plc["thread"].get_latest_data()

    def get_all_latest_data(self) -> Dict[str, Dict[str, list]]:
        """
        Получить последние данные от polls всех устройств

        Returns:
            dict: {plc_id: {poll_name: data}}
        """
        result = {}
        for plc_id in self.plcs.keys():
            data = self.get_latest_data(plc_id)
            if data:
                result[plc_id] = data
        return result

    # ==========================================================================
    # EXTENDED API - Методы с автоматическими преобразованиями
    # ==========================================================================

    def read_registers(
        self,
        plc_id: str,
        reg_type: str,
        address: int,
        count: int,
        format: str = "raw",
        byte_order: str = "ABCD",
        timeout: float = 5.0
    ) -> Optional[Union[List[int], float, int]]:
        """
        Чтение регистров с автоматическим преобразованием формата

        Args:
            plc_id: ID устройства
            reg_type: Тип регистра ("holding", "input", "coil", "discrete")
            address: Адрес начального регистра
            count: Количество регистров
            format: Формат преобразования:
                - "raw" (по умолчанию) - список регистров [int, int, ...]
                - "float32" - float из 2 регистров
                - "float64" - float из 4 регистров
                - "int32" - signed int из 2 регистров
                - "uint32" - unsigned int из 2 регистров
                - "int16_signed" - преобразовать регистры в signed int16
            byte_order: Порядок байт ("ABCD", "BADC", "CDAB", "DCBA")
            timeout: Таймаут ожидания результата (секунды)

        Returns:
            - Для "raw": List[int] - список регистров
            - Для "float32", "float64": float - значение
            - Для "int32", "uint32": int - значение
            - Для "int16_signed": List[int] - список signed значений
            - None при ошибке

        Example:
            # Чтение сырых регистров
            data = backend.read_registers("PLC1", "holding", 0, 2)
            # -> [12345, 54321]

            # Чтение float32
            temp = backend.read_registers("PLC1", "holding", 0, 2, format="float32")
            # -> 25.5

            # Чтение int32
            counter = backend.read_registers("PLC1", "holding", 10, 2, format="int32")
            # -> -12345
        """
        plc = self.plcs.get(plc_id)
        if not plc or not plc["connected"] or not plc.get("thread"):
            return None

        try:
            result = self._execute_and_wait(plc_id, ("read", reg_type, address, count), timeout)

            if format == "raw":
                return result
            elif format == "float32":
                if len(result) < 2:
                    return None
                return ConvertProtocolData.convert_4bytes([result[0], result[1]], "float32", byte_order)
            elif format == "float64":
                if len(result) < 4:
                    return None
                import struct
                bytes_data = b''.join(r.to_bytes(2, 'big') for r in result[:4])
                return struct.unpack('>d', bytes_data)[0]
            elif format == "int32":
                if len(result) < 2:
                    return None
                return ConvertProtocolData.convert_4bytes([result[0], result[1]], "int32", byte_order)
            elif format == "uint32":
                if len(result) < 2:
                    return None
                return ConvertProtocolData.convert_4bytes([result[0], result[1]], "uint32", byte_order)
            elif format == "int16_signed":
                return [ConvertProtocolData.to_signed_16(v) for v in result]
            else:
                return None

        except Exception:
            return None

    def write_registers(
        self,
        plc_id: str,
        reg_type: str,
        address: int,
        value: Union[List[int], float, int],
        format: str = "raw",
        byte_order: str = "ABCD",
        timeout: float = 5.0
    ) -> bool:
        """
        Запись регистров с автоматическим преобразованием формата

        Args:
            plc_id: ID устройства
            reg_type: Тип регистра ("holding", "coil")
            address: Адрес начального регистра
            value: Значение для записи (зависит от формата)
            format: Формат преобразования:
                - "raw" (по умолчанию) - список регистров [int, int, ...]
                - "float32" - float -> 2 регистра
                - "float64" - float -> 4 регистра
                - "int32" - int -> 2 регистра
                - "uint32" - int -> 2 регистра
            byte_order: Порядок байт ("ABCD", "BADC", "CDAB", "DCBA")
            timeout: Таймаут ожидания результата (секунды)

        Returns:
            bool: True при успехе, False при ошибке

        Example:
            # Запись сырых регистров
            backend.write_registers("PLC1", "holding", 0, [100, 200])

            # Запись float32
            backend.write_registers("PLC1", "holding", 0, 25.5, format="float32")

            # Запись int32
            backend.write_registers("PLC1", "holding", 10, -12345, format="int32")
        """
        plc = self.plcs.get(plc_id)
        if not plc or not plc["connected"] or not plc.get("thread"):
            return False

        try:
            # Преобразуем значение в список регистров
            if format == "raw":
                if not isinstance(value, list):
                    return False
                registers = value
            elif format == "float32":
                if not isinstance(value, (int, float)):
                    return False
                registers = ConvertProtocolData.convert_4bytes(float(value), "float32", byte_order)
            elif format == "float64":
                if not isinstance(value, (int, float)):
                    return False
                # Float64 через struct
                import struct
                bytes_data = struct.pack('>d', float(value))
                registers = [int.from_bytes(bytes_data[i:i+2], 'big') for i in range(0, 8, 2)]
            elif format == "int32":
                if not isinstance(value, int):
                    return False
                registers = ConvertProtocolData.convert_4bytes(value, "int32", byte_order)
            elif format == "uint32":
                if not isinstance(value, int):
                    return False
                registers = ConvertProtocolData.convert_4bytes(value, "uint32", byte_order)
            else:
                return False

            self._execute_and_wait(plc_id, ("write", reg_type, address, len(registers), registers), timeout)
            return True

        except Exception:
            return False

    def read_bit(
        self,
        plc_id: str,
        address: int,
        bit_number: int,
        timeout: float = 5.0
    ) -> Optional[int]:
        """
        Чтение одного бита из holding регистра

        Args:
            plc_id: ID устройства
            address: Адрес регистра
            bit_number: Номер бита (0-15)
            timeout: Таймаут ожидания (секунды)

        Returns:
            int: 0 или 1, None при ошибке

        Example:
            bit = backend.read_bit("PLC1", 100, 5)
            if bit == 1:
                print("Bit 5 is SET")
        """
        if not (0 <= bit_number <= 15):
            return None

        # Читаем регистр
        result = self.read_registers(plc_id, "holding", address, 1, format="raw", timeout=timeout)
        if result is None or len(result) == 0:
            return None

        # Извлекаем бит
        try:
            bit_value = ConvertProtocolData.register_bits(result[0], bit=bit_number)
            return bit_value
        except Exception as e:
            return None

    def write_bit(
        self,
        plc_id: str,
        address: int,
        bit_number: int,
        value: int,
        timeout: float = 5.0
    ) -> bool:
        """
        Запись одного бита в holding регистр (read-modify-write)

        Args:
            plc_id: ID устройства
            address: Адрес регистра
            bit_number: Номер бита (0-15)
            value: Значение бита (0 или 1)
            timeout: Таймаут ожидания (секунды)

        Returns:
            bool: True при успехе, False при ошибке

        Example:
            # Set bit 5
            backend.write_bit("PLC1", 100, 5, 1)

            # Clear bit 3
            backend.write_bit("PLC1", 100, 3, 0)
        """
        if not (0 <= bit_number <= 15) or value not in (0, 1):
            return False

        # Читаем текущее значение регистра
        result = self.read_registers(plc_id, "holding", address, 1, format="raw", timeout=timeout)
        if result is None or len(result) == 0:
            return False

        try:
            old_value = result[0]

            # Получаем биты
            bits = ConvertProtocolData.register_bits(old_value)

            # Модифицируем нужный бит
            bits[bit_number] = value

            # Собираем обратно в регистр
            new_value = ConvertProtocolData.register_bits(bits)

            # Записываем
            return self.write_registers(plc_id, "holding", address, [new_value], format="raw", timeout=timeout)

        except Exception as e:
            return False

    def toggle_bit(
        self,
        plc_id: str,
        address: int,
        bit_number: int,
        timeout: float = 5.0
    ) -> bool:
        """
        Переключение (toggle) одного бита в holding регистре

        Args:
            plc_id: ID устройства
            address: Адрес регистра
            bit_number: Номер бита (0-15)
            timeout: Таймаут ожидания (секунды)

        Returns:
            bool: True при успехе, False при ошибке

        Example:
            # Toggle bit 7
            backend.toggle_bit("PLC1", 100, 7)
        """
        # Читаем текущее значение бита
        current_bit = self.read_bit(plc_id, address, bit_number, timeout=timeout)
        if current_bit is None:
            return False

        # Инвертируем
        new_bit = 1 - current_bit

        # Записываем
        return self.write_bit(plc_id, address, bit_number, new_bit, timeout=timeout)

    # ==========================================================================
    # LIFECYCLE
    # ==========================================================================

    def stop_all(self):
        """
        Остановить все устройства и очистить backend

        ВАЖНО: Вызывать при завершении приложения для корректного cleanup
        """
        # Отключаем все устройства (блокирующий режим для корректного завершения)
        self.disconnect_all(blocking=True)

    # ==========================================================================
    # INTERNAL SIGNAL HANDLERS
    # ==========================================================================

    def _on_device_connected(self, plc_id: str):
        """Обработчик успешного подключения устройства"""
        plc = self.plcs.get(plc_id)
        if plc:
            plc["connected"] = True

        # Вызываем callback
        if self.on_connected:
            self.on_connected(plc_id)

        # Эмитим signal
        self.device_connected.emit(plc_id)

    def _on_device_disconnected(self, plc_id: str):
        """Обработчик отключения устройства"""
        plc = self.plcs.get(plc_id)
        if plc:
            plc["connected"] = False
            plc["thread"] = None

        # Вызываем callback
        if self.on_disconnected:
            self.on_disconnected(plc_id)

        # Эмитим signal
        self.device_disconnected.emit(plc_id)

    def _on_device_error(self, plc_id: str, error: str):
        """Обработчик ошибки устройства"""
        # Вызываем callback
        if self.on_connection_error:
            self.on_connection_error(plc_id, error)

        # Эмитим signal
        self.device_error.emit(plc_id, error)

    def _on_command_result(self, plc_id: str, result):
        """Обработчик результата команды"""
        # Разрешаем pending future для синхронных методов (не затрагивает глобальные callbacks)
        with self._pending_lock:
            fut = self._pending_futures.get(plc_id)
        if fut and not fut.done():
            fut.set_result(result)

        # Вызываем глобальный callback
        if self.on_command_completed:
            self.on_command_completed(plc_id, result)

    def _on_command_error(self, plc_id: str, error: str):
        """Обработчик ошибки команды"""
        # Разрешаем pending future с исключением
        with self._pending_lock:
            fut = self._pending_futures.get(plc_id)
        if fut and not fut.done():
            fut.set_exception(Exception(error))

        # Вызываем глобальный callback
        if self.on_command_error:
            self.on_command_error(plc_id, error)

    def _on_data_updated(self, plc_id: str, poll_name: str, data: dict):
        """Обработчик обновления данных от poll"""
        # Вызываем callback
        if self.on_data_updated:
            self.on_data_updated(plc_id, poll_name, data)

        # Эмитим signal
        self.data_updated.emit(plc_id, poll_name, data)
