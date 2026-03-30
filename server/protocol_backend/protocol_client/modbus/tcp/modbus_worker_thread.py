"""
PLCWorkerThread - QThread обертка для AsyncPLCWorker
Каждый PLC работает в отдельном потоке с собственным asyncio event loop.
Паттерн: OpcUaWorker из src/communication/protocols/opc_ua.py
"""

import asyncio
import threading
from typing import Optional, Dict
from PyQt6.QtCore import QThread, pyqtSignal

from .modbus_worker import AsyncPLCWorker


class PLCWorkerThread(QThread):
    """QThread обертка для AsyncPLCWorker с собственным asyncio event loop"""

    # === SIGNALS для коммуникации с GUI ===
    loop_ready = pyqtSignal()  # Event loop готов к работе (НОВЫЙ!)
    connected = pyqtSignal()  # Успешное подключение
    disconnected = pyqtSignal()  # Отключение
    connection_error = pyqtSignal(str)  # Ошибка подключения
    data_updated = pyqtSignal(str, dict)  # (poll_name, data) - обновление данных из poll
    command_completed = pyqtSignal(object)  # Результат выполнения команды
    command_error = pyqtSignal(str)  # Ошибка выполнения команды

    def __init__(self, plc_id: str, host: str, port: int = 502, device_id: int = 1):
        """
        Инициализация worker thread для PLC

        Args:
            plc_id: Уникальный идентификатор PLC
            host: IP адрес устройства
            port: Modbus TCP порт (по умолчанию 502)
            device_id: Modbus slave ID (по умолчанию 1)
        """
        super().__init__()
        self.plc_id = plc_id
        self.host = host
        self.port = port
        self.device_id = device_id

        # Event loop и worker будут созданы в run()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.worker: Optional[AsyncPLCWorker] = None
        self._connected = False
        self._stopping = False  # Флаг остановки (для неблокирующего stop)

        # Thread-safe доступ к latest_data
        self._latest_data_lock = threading.Lock()
        self._latest_data: Dict[str, list] = {}
        self._latest_data_changed = False  # Флаг изменения данных (оптимизация GUI)
        self._latest_data_hash: Optional[str] = None  # Hash для быстрого сравнения (оптимизация)

    def run(self):
        """
        Создание event loop в потоке и запуск (паттерн OpcUaWorker)
        Этот метод выполняется в отдельном потоке

        ОПТИМИЗАЦИЯ: Эмитим signal loop_ready когда loop готов к работе.
        Это избавляет от QTimer.singleShot(100) в GUI коде.
        """
        # Создаем новый event loop для этого потока
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # ===== ЭМИТИМ SIGNAL loop_ready =====
        # Теперь GUI может безопасно вызывать thread-safe методы
        # Не нужно ждать фиксированное время (QTimer.singleShot)
        self.loop_ready.emit()

        # Запускаем event loop (блокирующий вызов до stop())
        self.loop.run_forever()

        # Cleanup после остановки loop
        self.loop.close()

    def stop(self, blocking: bool = True):
        """
        Корректная остановка потока.
        Thread-safe метод, вызывается из главного потока.

        Args:
            blocking: True - блокирующий режим, False - неблокирующий (не блокирует GUI)
        """
        if self._stopping:
            return

        self._stopping = True

        if not self.loop or not self.loop.is_running():
            return

        if self._connected and self.worker:
            # disconnect и stop loop — одна корутина, гарантирует порядок
            future = asyncio.run_coroutine_threadsafe(
                self._async_disconnect_and_stop(), self.loop
            )
            if blocking:
                try:
                    future.result(timeout=5.0)
                except Exception as e:
                    print(f"[{self.plc_id}] Ошибка при остановке: {e}")
        else:
            self.loop.call_soon_threadsafe(self.loop.stop)

        if blocking:
            self.wait()
            self.deleteLater()

    # ==========================================================================
    # PUBLIC METHODS (thread-safe, вызываются из GUI потока)
    # ==========================================================================

    def is_loop_ready(self) -> bool:
        """
        Проверка готовности event loop

        Returns:
            bool: True если loop создан и работает
        """
        return self.loop is not None and self.loop.is_running()

    def connect_to_plc(self):
        """
        Thread-safe подключение к PLC
        Вызывается из главного потока, выполняется в worker потоке

        ОПТИМИЗАЦИЯ: Проверяем готовность loop перед вызовом.
        """
        if self.is_loop_ready():
            asyncio.run_coroutine_threadsafe(
                self._async_connect(), self.loop
            )

    def disconnect_from_plc(self):
        """
        Thread-safe отключение от PLC
        Вызывается из главного потока, выполняется в worker потоке
        """
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._async_disconnect(), self.loop
            )

    def execute_command(self, command: tuple):
        """
        Thread-safe выполнение команды (read/write)

        Args:
            command: tuple вида ("read", type, address, count) или ("write", type, address, count, value)
        """
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._async_execute_command(command), self.loop
            )

    def add_poll(self, poll_config: dict):
        """
        Thread-safe добавление циклического опроса

        Args:
            poll_config: dict с ключами: name, type, address, count, interval
        """
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self._async_add_poll(poll_config), self.loop
            )

    def get_latest_data(self) -> dict:
        """
        Thread-safe получение последних данных из polls

        Returns:
            dict: Копия latest_data {poll_name: data}
        """
        with self._latest_data_lock:
            return self._latest_data.copy()

    def has_data_changed(self, reset: bool = True) -> bool:
        """
        Проверка изменения данных с момента последней проверки

        ОПТИМИЗАЦИЯ: Позволяет GUI обновлять таблицы только при изменении данных.

        Args:
            reset: Сбросить флаг после проверки (по умолчанию True)

        Returns:
            bool: True если данные изменились
        """
        with self._latest_data_lock:
            changed = self._latest_data_changed
            if reset:
                self._latest_data_changed = False
            return changed

    # ==========================================================================
    # PRIVATE ASYNC METHODS (выполняются в event loop потока)
    # ==========================================================================

    async def _async_connect(self):
        """
        Создание и запуск AsyncPLCWorker
        Выполняется в event loop worker потока

        ОПТИМИЗАЦИЯ: Убрали фиксированную задержку await asyncio.sleep(0.5).
        Подключение происходит мгновенно, т.к. _command_loop работает в фоне.
        """
        try:
            # Создаем AsyncPLCWorker
            self.worker = AsyncPLCWorker(
                self.plc_id, self.host, self.port, self.device_id
            )

            # Запускаем worker (создает _command_loop)
            # _command_loop работает в фоне и сразу готов принимать команды
            asyncio.create_task(self.worker.start())

            # Отмечаем как подключенный
            self._connected = True

            # Сигнализируем об успешном подключении
            self.connected.emit()

            # Запускаем loop для синхронизации latest_data
            asyncio.create_task(self._sync_latest_data_loop())

        except Exception as e:
            # Сигнализируем об ошибке
            self.connection_error.emit(str(e))

    async def _async_disconnect_and_stop(self):
        """Disconnect + остановка loop одной корутиной — гарантирует порядок."""
        await self._async_disconnect()
        self.loop.stop()

    async def _async_disconnect(self):
        """
        Остановка AsyncPLCWorker
        Выполняется в event loop worker потока
        """
        if self.worker:
            try:
                await self.worker.stop()
                self.worker = None
            except Exception as e:
                print(f"[{self.plc_id}] Ошибка остановки worker: {e}")

        self._connected = False
        self.disconnected.emit()

    async def _async_execute_command(self, command: tuple):
        """
        Выполнение команды read/write через AsyncPLCWorker

        Args:
            command: tuple команды для AsyncPLCWorker.request()
        """
        try:
            if not self.worker:
                self.command_error.emit("Worker не инициализирован")
                return

            # Выполняем команду через worker
            result = await self.worker.request(command)

            # Отправляем результат в GUI
            self.command_completed.emit(result)

        except Exception as e:
            # Отправляем ошибку в GUI
            self.command_error.emit(str(e))

    async def _async_add_poll(self, poll_config: dict):
        """
        Добавление poll loop в AsyncPLCWorker

        Args:
            poll_config: dict с параметрами опроса
        """
        try:
            if not self.worker:
                return

            # Создаем задачу poll_loop
            task = asyncio.create_task(self.worker._poll_loop(poll_config))

            # Добавляем в список задач worker (для отмены при stop)
            self.worker._poll_tasks.append(task)

        except Exception as e:
            print(f"[{self.plc_id}] Ошибка добавления poll: {e}")

    async def _sync_latest_data_loop(self):
        """
        Периодическое копирование latest_data из worker и отправка signals
        Этот loop синхронизирует данные между worker и GUI

        ОПТИМИЗАЦИЯ: Устанавливаем флаг _latest_data_changed только при реальном изменении.
        ОПТИМИЗАЦИЯ: Используем hash-based сравнение для быстрой проверки изменений.
        """
        while self._connected and not self._stopping:
            if self.worker:
                # Получаем данные от worker
                worker_data = self.worker.latest_data.copy()

                # Вычисляем hash данных для быстрого сравнения (O(1) вместо O(n))
                import hashlib
                import json
                try:
                    # Сериализуем данные в JSON (sorted keys для консистентности)
                    data_str = json.dumps(worker_data, sort_keys=True, default=str)
                    data_hash = hashlib.md5(data_str.encode()).hexdigest()
                except (TypeError, ValueError):
                    # Fallback на прямое сравнение если не удается сериализовать
                    data_hash = str(hash(str(worker_data)))

                # Проверяем, изменились ли данные (hash сравнение быстрее)
                data_changed = False
                with self._latest_data_lock:
                    if self._latest_data_hash != data_hash:
                        self._latest_data = worker_data
                        self._latest_data_hash = data_hash
                        self._latest_data_changed = True
                        data_changed = True

                # Отправляем сигналы только если данные изменились
                if data_changed:
                    for poll_name, data in worker_data.items():
                        self.data_updated.emit(poll_name, {"data": data})

            # Интервал синхронизации 500мс
            await asyncio.sleep(0.5)
