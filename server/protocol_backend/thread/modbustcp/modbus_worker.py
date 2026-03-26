import asyncio
from asyncio import Queue
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

# Асинхронный воркер для работы с Modbus TCP устройствами
class AsyncPLCWorker:

# Инициализация воркера для работы с Modbus устройством
    def __init__(self, plc_id: str, host: str, port: int = 502, device_id: int = 1):
        # Имя устройства
        self.plc_id = plc_id          
        # IP адрес устройства
        self.host = host     
        # Порт         
        self.port = port  
        # Slave id           
        self.device_id = device_id    

        # Очередь для команд (thread-safe)
        self.queue: Queue = Queue()
        # Флаг работы (для остановки всех задач)
        self._running = True
        # Хранилище последних данных из poll_loops
        self.latest_data = {}
        # Список задач циклических опросов (для отмены при остановке)
        self._poll_tasks = []

# Запуск воркера: создает задачи циклических опросов и запускает обработку команд.
    async def start(self, polls: list = None):
        # Запуск циклических опросов (если есть)
        if polls:
            for poll in polls:
                # Создаем отдельную задачу для каждого опроса
                task = asyncio.create_task(self._poll_loop(poll))
                # Сохраняем для последующей отмены
                self._poll_tasks.append(task)  
        # Запуск основного цикла обработки команд (блокирующий вызов)
        await self._command_loop()

# Основной цикл обработки команд из очереди.
    async def _command_loop(self):
        # Создаем постоянное соединение с устройством
        async with AsyncModbusTcpClient(self.host, port=self.port) as client:
            # Инициализация словарей методов для быстрого поиска
            self._init_method_maps(client)
            # Основной цикл обработки команд
            while self._running:
                # Получаем команду из очереди
                future, request = await self.queue.get()
                # Команда остановки
                if future is None:
                    # Выходим из цикла
                    break
                # Пытаемся выполнить команду
                try:
                    # Распаковываем команду: команда, тип регистра, адрес, количество, доп.аргументы
                    cmd, type_, address, count, *args = request
                    # Словарь обработчиков команд (вместо if-elif)
                    handlers = {
                        "read": lambda: self._read_modbus(client, type_, address, count),
                        "write": lambda: self._write_modbus(client, type_, address, args[0])
                    }
                    # Выбираем обработчик по типу команды
                    handler = handlers.get(cmd)
                    # Проверяем, что команда известна
                    if not handler:
                        raise ValueError(f"Unknown command: {cmd}")
                    # Выполняем команду и получаем результат
                    result = await handler()
                    # Передаем результат в future
                    future.set_result(result)
                # Обрабатываем любые ошибки выполнения команды
                except Exception as exc:
                    # Передаем исключение в future (для обработки в вызывающем коде)
                    future.set_exception(exc)

# Инициализация словарей методов чтения/записи для быстрого доступа
    def _init_method_maps(self, client):
        # Словарь методов чтения: тип -> (метод_клиента, атрибут_результата)
        self._read_methods = {
            "holding": (client.read_holding_registers, "registers"),
            "input": (client.read_input_registers, "registers"),
            "coil": (client.read_coils, "bits"),
            "discrete": (client.read_discrete_inputs, "bits")
        }
        # Словарь методов записи: тип -> (метод_клиента, имя_параметра)
        self._write_methods = {
            "holding": (client.write_register, "value"),
            "holdings": (client.write_registers, "values"),
            "coil": (client.write_coil, "value"),
            "coils": (client.write_coils, "values")
        }
# Чтение данных из Modbus регистров.
    async def _read_modbus(self, client, type_, address, count):
        # Получаем метод и атрибут из словаря (O(1) вместо O(n))
        method_info = self._read_methods.get(type_)
        # Проверяем, что тип регистра поддерживается
        if not method_info:
            raise ValueError(f"Unknown read type: {type_}")
        # Распаковываем метод и атрибут результата
        method, attr = method_info
        # Выполняем чтение через соответствующий метод клиента
        result = await method(address=address, count=count, device_id=self.device_id)
        # Извлекаем нужный атрибут из результата (registers или bits)
        return getattr(result, attr)

# Запись данных в Modbus регистры
    async def _write_modbus(self, client, type_, address, value):

        # Получаем метод и имя параметра из словаря (O(1))
        method_info = self._write_methods.get(type_)
        # Проверяем, что тип регистра поддерживается
        if not method_info:
            raise ValueError(f"Unknown write type: {type_}")
        # Распаковываем метод и имя параметра
        method, param_name = method_info
        # Выполняем запись через соответствующий метод клиента
        await method(address=address, **{param_name: value}, device_id=self.device_id)
        # Возвращаем успешный результат
        return True

# Циклический опрос регистров с заданным интервалом
    async def _poll_loop(self, poll: dict):
        # Компактная распаковка параметров опроса
        name, address, count = poll["name"], poll["address"], poll["count"]
        # Получаем интервал опроса (по умолчанию 2 сек) и тип регистра (по умолчанию holding)
        interval, type_ = poll.get("interval", 2.0), poll.get("type", "holding")
        # Создаем отдельное соединение для этого опроса
        async with AsyncModbusTcpClient(self.host, port=self.port) as client:
            # Инициализируем словари методов для этого соединения
            self._init_method_maps(client)
            # Бесконечный цикл опроса
            while self._running:
                # Пытаемся прочитать данные
                try:
                    # Читаем регистры и сохраняем в latest_data
                    self.latest_data[name] = await self._read_modbus(client, type_, address, count)
                # Обрабатываем любые ошибки чтения
                except Exception:
                    # Игнорируем ошибки (потеря связи и т.д.)
                    pass
                # Ждем перед следующим опросом
                await asyncio.sleep(interval)

# Отправка команды в очередь для выполнения и ожидание результата
    async def request(self, command: tuple):
        # Получаем текущий event loop
        loop = asyncio.get_running_loop()
        # future для получения результата и будет заполнен в command_loop после выполнения команды
        future = loop.create_future()
        # Помещаем команду в очередь (thread-safe) command_loop извлечет ее и выполнит
        await self.queue.put((future, command))
        # Ожидаем выполнения команды и возвращаем результат
        return await future

# Остановка воркера: завершает все циклы опросов и обработку команд
    async def stop(self):
        # Останавливаем все циклы
        self._running = False
        # Отправляем команду остановки в command_loop (None, None) - специальное значение для выхода из цикла
        await self.queue.put((None, None))
        # Отменяем все задачи циклических опросов
        for task in self._poll_tasks:
            # Отмена задачи (вызовет CancelledError в задаче)
            task.cancel()
