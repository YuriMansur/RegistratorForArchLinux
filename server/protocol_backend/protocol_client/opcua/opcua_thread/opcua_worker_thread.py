"""
Обёртка для AsyncOpcUaWorker.
Каждый OPC UA сервер работает в отдельном потоке с собственным асинхронным циклом событий.
"""
# Для асинхронных операций и цикла событий
import asyncio
# Для вынесения в отдельный поток, чтобы не блокировать основной поток приложения.
import threading
# Для логирования ошибок и событий.
import logging
# Для типизации и удобства разработки.
from typing import Optional, Dict, Any, List, Callable

# Логгер для этого модуля
log = logging.getLogger(__name__)

# Вспомогательная функция для безопасного вызова callback-ов, чтобы ошибки внутри них не прерывали работу потока.
def _call(cb: Optional[Callable], *args):
    """Безопасный вызов callback."""
    # Если callback не задан, просто игнорируем вызов.
    if cb:
        try:
            # Вызываем callback с переданными аргументами. 
            # Если внутри callback возникнет ошибка, она будет поймана и залогирована, чтобы не нарушать работу потока.
            cb(*args)
        # Если при вызове callback возникла ошибка.
        except Exception as e:
            # Логируем ошибку при вызове callback, но не даём ей прервать работу потока,
            # так как это может привести к зависанию или некорректной работе.
            log.error("Callback error: %s", e)

# Основной класс — поток с AsyncOpcUaWorker и собственным event loop.
class OpcUaWorkerThread(threading.Thread):
    """Thread обёртка для AsyncOpcUaWorker с собственным asyncio loop."""

    def __init__(self, server_id : str, endpoint : str, namespace: int = 2, timeout: float = 10.0):
        """
        Инициализация потока и его атрибутов.
        Args:
            server_id (str): Идентификатор сервера.
            endpoint (str): URL endpoint OPC UA.
            namespace (int): Номер namespace для тегов.
            timeout (float): Таймаут для операций чтения/записи в секундах.
        """
        super().__init__(daemon = True, name = f"opcua-{server_id}")
            # deamon (bool): Устанавливает поток как демона, чтобы он не блокировал завершение программы.
            # name (str): Человеко-читаемое имя потока для логов и отладки.
       
# Инициализация атрибутов потока и сигнальных callback-ов для событий от AsyncOpcUaWorker.

        self.server_id  = server_id
        """Идентификатор сервера — используется в логах и для различения нескольких серверов."""
        self.endpoint   = endpoint
        """OPC UA endpoint URL, например "opc.tcp://localhost:4840"."""
        self.namespace  = namespace
        """Номер namespace для тегов — обычно 2, но может отличаться в зависимости от сервера."""
        self.timeout    = timeout
        """Таймаут для операций чтения/записи в секундах."""
        self.loop:   Optional[asyncio.AbstractEventLoop] = None
        """Asyncio event loop, созданный в run()."""
        self.worker: Optional[Any] = None
        """AsyncOpcUaWorker — будет создан в run() после запуска потока."""
        self._connected         = False
        """Флаг остановки потока — чтобы не пытаться перезапустить его, если уже идёт завершение."""
        self._stopping          = False
        """Флаг подключения к серверу — True после успешного подключения, False после отключения."""
        self._loop_ready        = False
        """Флаг готовности event loop — True после запуска loop, до этого нельзя ставить задачи в очередь."""
        self._latest_data_lock  = threading.Lock()
        """Блокировка для доступа к _latest_data и _data_changed_flag."""
        self._latest_data:      Dict[str, Any] = {}
        """Последние полученные значения тегов — node_id → value."""
        self._data_changed_flag = False
        """Флаг, указывающий, что с момента последнего вызова get_latest_data() были изменения данных."""

 # Сигналы (callable callbacks) для событий и данных от AsyncOpcUaWorker

        self.on_loop_ready:                  Optional[Callable]                  = None
        """Сигнал: event loop запущен и готов принимать задачи."""
        self.on_connected:                   Optional[Callable]                  = None
        """Сигнал: успешно подключились к серверу."""
        self.on_disconnected:                Optional[Callable]                  = None
        """Сигнал: отключились от сервера (по любой причине)."""
        self.on_connection_error:            Optional[Callable[[str], None]]     = None
        """Сигнал: ошибка при подключении или в процессе работы. Аргумент — текст ошибки."""
        self.on_data_updated:                Optional[Callable[[str, Any], None]]= None
        """Сигнал: получили новое значение тега. Аргументы — node_id и value."""
        self.on_tag_subscribed:              Optional[Callable[[str], None]]     = None
        """Сигнал: успешно подписались на тег. Аргумент — node_id."""
        self.on_tag_unsubscribed:            Optional[Callable[[str], None]]     = None
        """Сигнал: отписались от тега. Аргумент — node_id."""
        self.on_read_completed:              Optional[Callable[[str, Any], None]]= None
        """Сигнал: завершилось чтение одного узла. Аргументы — node_id и value."""
        self.on_write_completed:             Optional[Callable[[str, bool], None]]= None
        """Сигнал: завершилась запись одного узла. Аргументы — node_id и success."""
        self.on_batch_read_completed:        Optional[Callable[[dict], None]]    = None
        """Сигнал: завершилось чтение нескольких узлов. Аргумент — dict node_id → value."""
        self.on_batch_write_completed:       Optional[Callable[[dict], None]]    = None
        """Сигнал: завершилась запись нескольких узлов. Аргумент — dict node_id → success."""
        self.on_poll_batch:                  Optional[Callable[[str, dict], None]]= None
        """Сигнал: завершился один цикл poll. Аргументы — имя группы и dict node_id → value."""
        self.on_watchdog_disconnect:         Optional[Callable]                  = None
        """Сигнал: watchdog обнаружил пропажу связи с сервером."""
        self.on_browse_completed:            Optional[Callable[[list], None]]    = None
        """Сигнал: завершилось исследование узлов. Аргумент — список найденных узлов."""
        self.on_node_info_completed:         Optional[Callable[[dict], None]]    = None
        """Сигнал: завершилось чтение информации об узле. Аргумент — dict с данными узла."""


# Поток + цикл событий


    # Старт потока и цикла событий
    def run(self):
        """Точка входа в поток — создаёт event loop, AsyncOpcUaWorker и запускает loop."""
        # Создаём новый event loop для этого потока и устанавливаем его как текущий.
        self.loop = asyncio.new_event_loop()
        # Важно: set_event_loop нужно вызывать в том же потоке, в котором будет работать loop,
        # иначе могут быть проблемы с asyncio.
        # Поэтому мы вызываем его здесь, внутри run(), а не в конструкторе.
        asyncio.set_event_loop(self.loop)
        # Отключаем debug mode для asyncio, чтобы не было лишних предупреждений в логах.
        self.loop.set_debug(False)
        # Создаём AsyncOpcUaWorker, передавая ему callback для обработки новых данных от сервера.
        # Должен быть создан уже после запуска loop, так как внутри него может использоваться текущий event loop.
        from protocol_backend.protocol_client.opcua.opcua_worker.opcua_worker import AsyncOpcUaWorker
        """AsyncOpcUaWorker — основной класс, который реализует все операции с OPC UA сервером и работает внутри event loop этого потока."""
        """!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"""
        self.worker = AsyncOpcUaWorker(
            endpoint        = self.endpoint,
            namespace       = self.namespace,
            timeout         = self.timeout,
            on_data_changed = self._on_data_changed,
        )
        self.worker.on_poll_batch = lambda name, batch: _call(self.on_poll_batch, name, batch)
        # Запускаем корутину подключения к серверу — она будет выполняться в этом же event loop.
        self._loop_ready = True
        # Вызываем сигнал о готовности event loop, чтобы внешний код мог начать ставить задачи в очередь.
        _call(self.on_loop_ready)
        try:
            # Пробуем запускать event loop — он будет работать, пока не будет вызван loop.stop() в stop().
            self.loop.run_forever()
        finally:
            # При завершении работы loop нужно очистить ресурсы и закрыть его.
            self.loop.close()


    # Остановка потока и цикла событий
    def stop(self, blocking: bool = False):
        """Остановить event loop и завершить поток. Если blocking = True, будет ждать завершения до 2 секунд."""

        # Устанавливаем флаг остановки, чтобы не пытаться перезапустить поток, если он уже идёт на завершение.
        if self._stopping:
            return
        # Если поток уже идёт на завершение, не пытаемся остановить его повторно.
        self._stopping = True

        # Если loop и worker существуют, ставим задачу на отключение от сервера и остановку loop.
        if self.loop and self.worker:
            # Сначала отключаемся от сервера, чтобы корректно завершить все соединения и подписки.
            future = asyncio.run_coroutine_threadsafe(self._async_shutdown(), self.loop)
            # Ждём завершения задачи отключения, чтобы гарантировать корректное завершение соединений, особенно если сервер не отвечает.
            if blocking:
                try:
                    # Ждём завершения задачи отключения до 2 секунды
                    future.result(timeout = 2.0)
                    # Если отключение прошло успешно, loop должен быть остановлен, и поток завершится.
                except Exception:
                    pass
        # Если loop или worker не были созданы, просто устанавливаем флаг остановки и позволяем потоку завершиться.
        if blocking:
            self.join(2.0)


    # Проверка готовности цикла событий — чтобы не ставить задачи в очередь до его запуска
    def is_loop_ready(self) -> bool:
        """Проверить, что event loop запущен и готов принимать задачи."""
        return self._loop_ready and self.loop is not None


 # Подключение, отключение, чтение, запись, подписки и другие операции — ставят задачи в очередь event loop,
 # который выполняет их в AsyncOpcUaWorker.


    # Подключение и переподключение к серверу (вызывается при старте и при отключении от сервера)
    def connect_to_server(self):
        """
        Подключиться к серверу. Если уже подключены, ничего не делает. 
        Если отключились от сервера (по любой причине) — пытается переподключиться, если не идёт процесс остановки потока.
        """
        # При отключении от сервера (по любой причине) — пытаемся переподключиться, если не идёт процесс остановки потока.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на подключение к серверу — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_connect(), self.loop)


    # Обработчик новых данных от AsyncOpcUaWorker — сохраняет их в _latest_data и вызывает on_data_updated для каждого тега.
    async def _async_connect(self):
        """Подключиться к серверу — вызывается при старте потока и при отключении от сервера (по любой причине)."""
        try: 
            # Пытаемся подключиться к серверу
            success = await self.worker.connect()
            # Если подключение прошло успешно.
            if success:
                # Устанавливаем флаг подключения
                self._connected = True
                # Вызываем сигнал о подключении, чтобы внешний код мог реагировать на это событие.
                _call(self.on_connected)
        # Если при попытке подключения возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, str(e))


    # Отключение от сервера — вызывается при остановке потока или при отключении от сервера (по любой причине)
    async def _async_disconnect(self):
        """Отключиться от сервера — вызывается при остановке потока или при отключении от сервера (по любой причине)."""
        try:
            # Пытаемся отключиться от сервера
            await self.worker.disconnect()
            # Устанавливаем флаг отключения
            self._connected = False
            # Вызываем сигнал об отключении, чтобы внешний код мог реагировать на это событие.
            _call(self.on_disconnected)
        # Если при попытке отключения возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, str(e))


    # Обработчик новых данных от AsyncOpcUaWorker — сохраняет их в _latest_data и вызывает on_data_updated для каждого тега.
    async def _async_shutdown(self):
        """Отключиться от сервера и остановить event loop — вызывается при остановке потока."""
        # Сначала отключаемся от сервера, чтобы корректно завершить все соединения и подписки.
        if self._connected:
            try:
                # Пытаемся отключиться от сервера — это может занять некоторое время, особенно если сервер не отвечает,
                # поэтому важно делать это до остановки loop.
                await self.worker.disconnect()
                # Устанавливаем флаг отключения
                self._connected = False
                # Вызываем сигнал об отключении, чтобы внешний код мог реагировать на это событие.
                _call(self.on_disconnected)
            # Если при попытке отключения возникла ошибка, логируем её и продолжаем остановку loop, чтобы не зависнуть.
            except Exception as e:
                # Вызываем сигнал ошибки с текстом ошибки, но продолжаем остановку loop, чтобы гарантировать завершение потока.
                _call(self.on_connection_error, str(e))
        # После отключения от сервера останавливаем event loop, чтобы завершить работу потока.
        self.loop.stop()


# Чтение и запись узлов, подписки и другие операции — вызываются из внешнего кода, ставят задачи в очередь event loop.


    # Чтение одного узла
    def read_node(self, node_id: str):
        """Прочитать значение узла. Результат будет передан в on_read_completed."""
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на чтение узла — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_read_node(node_id), self.loop)


    # Чтение одного узла, асинхронная часть — выполняется в event loop, вызывает on_read_completed при завершении.
    async def _async_read_node(self, node_id: str):
        """Асинхронная часть чтения одного узла — выполняется в event loop, вызывает on_read_completed при завершении."""
        try:
            # Пытаемся прочитать значение узла
            value = await self.worker.read_node(node_id)
            # Вызываем сигнал о завершении чтения, передавая node_id и полученное значение.
            _call(self.on_read_completed, node_id, value)
        # Если при попытке чтения возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Read error: {e}")


    # Запись одного узла
    def write_node(self, node_id: str, value: Any):
        """Записать значение узла. Результат будет передан в on_write_completed."""
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на запись узла — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_write_node(node_id, value), self.loop)


    # Запись одного узла, асинхронная часть — выполняется в event loop, вызывает on_write_completed при завершении.
    async def _async_write_node(self, node_id: str, value: Any):
        """Асинхронная часть записи одного узла — выполняется в event loop, вызывает on_write_completed при завершении."""
        try:
            # Пытаемся записать значение узла
            success = await self.worker.write_node(node_id, value)
            # Вызываем сигнал о завершении записи, передавая node_id и результат (успех или неудача).
            _call(self.on_write_completed, node_id, success)
        # Если при попытке записи возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Write error: {e}")
            # В случае ошибки при записи мы считаем, что запись не удалась, и вызываем on_write_completed с success = False,
            _call(self.on_write_completed, node_id, False)


    # Чтение нескольких узлов
    def read_multiple_nodes(self, node_ids: List[str]):
        """Прочитать значения нескольких узлов. Результат будет передан в on_batch_read_completed в виде dict node_id → value."""
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на чтение нескольких узлов — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_read_multiple_nodes(node_ids), self.loop)


    #  Чтение нескольких узлов, асинхронная часть — выполняется в event loop, вызывает on_batch_read_completed при завершении.
    async def _async_read_multiple_nodes(self, node_ids: List[str]):
        """Асинхронная часть чтения нескольких узлов — выполняется в event loop, вызывает on_batch_read_completed при завершении."""
        try:
            # Пытаемся прочитать значения узлов — результат должен быть dict node_id → value
            results = await self.worker.read_multiple_nodes(node_ids)
            # Вызываем сигнал о завершении чтения, передавая dict node_id → value.
            _call(self.on_batch_read_completed, results)
        # Если при попытке чтения возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Batch read error: {e}")


    # Запись нескольких узлов
    def write_multiple_nodes(self, values: Dict[str, Any]):
        """Записать значения нескольких узлов. Результат будет передан в on_batch_write_completed в виде dict node_id → success."""
        if not self.is_loop_ready():
            raise RuntimeError("Event loop not ready")
        asyncio.run_coroutine_threadsafe(self._async_write_multiple_nodes(values), self.loop)

    # Запись нескольких узлов асинхронная часть
    async def _async_write_multiple_nodes(self, values: Dict[str, Any]):
        """
        Асинхронная часть записи нескольких узлов — выполняется в event loop,
          вызывает on_batch_write_completed при завершении.
          Args:
            values (Dict[str, Any]): Словарь с ID узлов и значениями для записи.
        """
        try:
            # Пытаемся записать значения узлов
            results = await self.worker.write_multiple_nodes(values)
            # Вызываем сигнал о завершении записи, передавая dict node_id → success.
            _call(self.on_batch_write_completed, results)
        # Если при попытке записи возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Batch write error: {e}")


# Подписки на теги — вызываются из внешнего кода, ставят задачи в очередь event loop, который выполняет их в AsyncOpcUaWorker.


    # Подписаться на тег
    def subscribe_tag(self, node_id: str, tag_name: Optional[str] = None):
        """Подписаться на тег. Результат будет передан в on_tag_subscribed при успешной подписке."""
        #  Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на подписку на тег — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_subscribe_tag(node_id, tag_name), self.loop)


    # Подписаться на тег, асинхронная часть
    async def _async_subscribe_tag(self, node_id: str, tag_name: Optional[str]):
        """Асинхронная часть подписки на тег — выполняется в event loop, вызывает on_tag_subscribed при успешной подписке."""
        try:
            # Пытаемся подписаться на тег
            success = await self.worker.subscribe_tag(node_id, tag_name)
            # Если подписка прошла успешно
            if success:
                # Вызываем сигнал о подписке, передавая node_id.
                _call(self.on_tag_subscribed, node_id)
        # Если при попытке подписки возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Subscribe error: {e}")


    # Отписаться от тега
    def unsubscribe_tag(self, node_id: str):
        """Отписаться от тега. Результат будет передан в on_tag_unsubscribed при успешной отписке."""
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на отписку от тега — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_unsubscribe_tag(node_id), self.loop)


    # Отписаться от тега, асинхронная часть
    async def _async_unsubscribe_tag(self, node_id: str):
        """Асинхронная часть отписки от тега — выполняется в event loop, вызывает on_tag_unsubscribed при успешной отписке."""
        try:
            #  Пытаемся отписаться от тега
            success = await self.worker.unsubscribe_tag(node_id)
            # Если отписка прошла успешно
            if success:
                # Вызываем сигнал об отписке, передавая node_id.
                _call(self.on_tag_unsubscribed, node_id)
        # Если при попытке отписки возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Unsubscribe error: {e}")


    # Подписаться на несколько тегов
    def subscribe_multiple_tags(self, tags: Dict[str, str]):
        """Подписаться на несколько тегов. Результат будет передан в on_tag_subscribed для каждого успешно подписанного тега.
        Args:
            tags (Dict[str, str]): Словарь node_id → tag_name для подписки на несколько тегов.
        """
        # Проверяем, что цикл событий запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если цикл событий не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на подписку на несколько тегов — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_subscribe_multiple_tags(tags), self.loop)

    # Подписаться на несколько тегов, асинхронная часть
    async def _async_subscribe_multiple_tags(self, tags: Dict[str, str]):
        """Асинхронная часть подписки на несколько тегов — выполняется в event loop,
        вызывает on_tag_subscribed для каждого успешно подписанного тега.
        Args:
            tags (Dict[str, str]): Словарь node_id → tag_name для подписки на несколько тегов.
        """
        try:
            # Пытаемся подписаться на несколько тегов — результат должен быть dict node_id → success
            results = await self.worker.subscribe_multiple_tags(tags)
            # Вызываем сигнал о подписке для каждого успешно подписанного тега, передавая node_id.
            for tag_name, success in results.items():
                # Если подписка на тег прошла успешно.
                if success:
                    # Вызываем сигнал о подписке, передавая node_id.
                    _call(self.on_tag_subscribed, tags[tag_name])
        # Если при попытке подписки возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Subscribe multiple error: {e}")


 # Периодический опрос узлов


    # Запуск периодического опроса узлов
    def start_polling(self, name: str, node_ids: List[str], interval: float = 1.0, sequential: bool = False):
        """Запустить периодический опрос узлов. Результаты будут переданы в on_data_updated для каждого полученного значения.
        Args:
            name (str): Уникальное имя опроса — используется для управления опросами (остановка, получение списка активных опросов).
            node_ids (List[str]): Список node_id для опроса.
            interval (float): Интервал опроса в секундах.
            sequential (bool): Если True, следующий опрос начнётся только после получения ответа на предыдущий,
            иначе опросы будут запускаться строго по таймеру, независимо"""
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на запуск периодического опроса узлов — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self.worker.start_polling(name, node_ids, interval, sequential), self.loop)


    # Остановка периодического опроса узлов
    def stop_polling(self, name: Optional[str] = None):
        """Остановить периодический опрос узлов. Если name = None, остановятся все опросы.
        Args:
            name (str | None): Уникальное имя опроса для остановки. Если None, остановятся все опросы.
        """
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            return
        # Ставим задачу на остановку периодического опроса узлов — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self.worker.stop_polling(name), self.loop)


    # Получение списка активных опросов
    def get_active_polls(self) -> Dict[str, Dict]:
        """
        Получить список активных опросов узлов. Результат — dict name → {node_ids, interval, sequential}.
        Если worker не создан, возвращает пустой dict.
        """
        # Если worker ещё не создан (например, поток только запустился), возвращаем пустой dict, чтобы избежать ошибок доступа к атрибуту.
        if not self.worker:
            return {}
        # Если event loop не готов, не пытаемся получать данные — это может привести к ошибкам.
        return self.worker.get_active_polls()


    # Проверка наличия активного опроса по имени
    def start_watchdog(self, interval: float = 5.0):
        """Запустить watchdog для мониторинга связи с сервером. Если связь пропадёт, будет вызван сигнал on_watchdog_disconnect.
        Args:
            interval (float): Интервал проверки связи в секундах."""

        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на запуск watchdog — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_start_watchdog(interval), self.loop)


    # Запуск watchdog, асинхронная часть
    async def _async_start_watchdog(self, interval: float):
        """
        Асинхронная часть запуска watchdog — выполняется в event loop,
        вызывает on_watchdog_disconnect при обнаружении пропажи связи с сервером.
            Args:
                interval (float): Интервал проверки связи в секундах.
        """
        # Запускаем watchdog в worker — он будет периодически проверять связь с сервером и вызывать on_watchdog_disconnect при её пропаже.
        await self.worker.start_watchdog(interval)
        # После запуска watchdog запускаем корутину для синхронизации его состояния
        # она будет следить за флагом is_watchdog_active и вызывать on_watchdog_disconnect, если связь пропала.
        asyncio.ensure_future(self._sync_watchdog_state())


    # Синхронизация состояния
    async def _sync_watchdog_state(self):
        """
        Асинхронная корутина для синхронизации состояния watchdog — выполняется в event loop,
        следит за флагом is_watchdog_active и вызывает on_watchdog_disconnect, если связь пропала.
        """
        # Пока watchdog активен
        while self.worker and self.worker.is_watchdog_active:
            # Подождём немного, чтобы не перегружать CPU постоянными проверками.
            await asyncio.sleep(0.5)
        # Если мы вышли из цикла, значит watchdog обнаружил пропажу связи с сервером — вызываем сигнал on_watchdog_disconnect,
        # если он ещё не был вызван.
        if self.worker and not self.worker.is_connected and self._connected:
            # Устанавливаем флаг отключения, чтобы не пытаться переподключиться, если уже идёт процесс отключения.
            self._connected = False
            # Вызываем сигнал о пропаже связи, чтобы внешний код мог реагировать на это событие.
            _call(self.on_watchdog_disconnect)
            # Также вызываем сигнал об отключении, так как с точки зрения внешнего кода это событие эквивалентно отключению от сервера.
            _call(self.on_disconnected)


    # Остановка watchdog
    def stop_watchdog(self):
        """Остановить watchdog для мониторинга связи с сервером."""
        if not self.is_loop_ready():
            return
        # Ставим задачу на остановку watchdog — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self.worker.stop_watchdog(), self.loop)


    # Проверка наличия активного watchdog
    @property
    def is_watchdog_active(self) -> bool:
        """Проверить, активен ли watchdog для мониторинга связи с сервером. Если worker не создан, возвращает False."""
        # Если worker ещё не создан (например, поток только запустился), возвращаем False, чтобы избежать ошибок доступа к атрибуту.
        return self.worker.is_watchdog_active if self.worker else False


# Сканирование


    # Обход дерева узлов сервера
    def browse_nodes(self, start_node_id: Optional[str] = None, depth: int = 1):
        """
        Обойти дерево узлов сервера, начиная с указанного узла.
        Результат передаётся в on_browse_completed в виде списка найденных узлов.

        Args:
            start_node_id (str | None): ID узла, с которого начинать обход. None — корень сервера.
            depth (int): Глубина обхода. 1 — только прямые дочерние узлы.
        """
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на обход дерева — она будет выполняться в event loop этого потока.
        asyncio.run_coroutine_threadsafe(self._async_browse_nodes(start_node_id, depth), self.loop)


    # Обход дерева узлов, асинхронная часть
    async def _async_browse_nodes(self, start_node_id, depth):
        """Асинхронная часть обхода узлов — выполняется в event loop, вызывает on_browse_completed при завершении.
        Args:
            start_node_id (str | None): ID узла, с которого начинать обход. None — корень сервера.
            depth (int): Глубина обхода. 1 — только прямые дочерние узлы.
        """
        try:
            # Запрашиваем список дочерних узлов у worker
            result = await self.worker.browse_nodes(start_node_id, depth)
            # Передаём список найденных узлов в callback
            _call(self.on_browse_completed, result)
        # Если при попытке обхода возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Browse error: {e}")


    # Чтение метаданных узла (тип, описание, атрибуты)
    def read_node_info(self, node_id: str):
        """
        Прочитать метаданные узла: тип данных, описание, атрибуты.
        Результат передаётся в on_node_info_completed в виде dict.

        Args:
            node_id (str): ID узла, о котором нужна информация.
        """
        # Проверяем, что event loop запущен и готов принимать задачи.
        if not self.is_loop_ready():
            # Если loop не готов, не пытаемся ставить задачи в очередь — это может привести к ошибкам.
            raise RuntimeError("Event loop not ready")
        # Ставим задачу на чтение метаданных узла.
        asyncio.run_coroutine_threadsafe(self._async_read_node_info(node_id), self.loop)


    # Чтение метаданных узла, асинхронная часть
    async def _async_read_node_info(self, node_id: str):
        """Асинхронная часть чтения метаданных узла — вызывает on_node_info_completed при завершении."""
        try:
            # Запрашиваем метаданные узла у worker
            result = await self.worker.read_node_info(node_id)
            # Передаём dict с метаданными в callback
            _call(self.on_node_info_completed, result)
        # Если при попытке чтения метаданных возникла ошибка
        except Exception as e:
            # Вызываем сигнал ошибки с текстом ошибки.
            _call(self.on_connection_error, f"Read node info error: {e}")


 # Данные и состояние


    # Обработчик новых данных
    def _on_data_changed(self, node_id: str, value: Any):
        """Обработчик новых данных от AsyncOpcUaWorker — сохраняет их в _latest_data и вызывает on_data_updated для каждого тега."""
        # Используем блокировку, чтобы гарантировать целостность данных при доступе из разных потоков.
        with self._latest_data_lock:
            # Сохраняем новое значение в _latest_data, используя node_id как ключ.
            # Это позволяет нам всегда иметь актуальные данные для каждого тега, на который есть подписка.
            self._latest_data[node_id] = value
            # Устанавливаем флаг, что данные были изменены с момента последнего вызова get_latest_data(),
            self._data_changed_flag = True
        # Вызываем сигнал о новом значении тега, передавая node_id и новое значение, чтобы внешний код мог реагировать на это событие.
        _call(self.on_data_updated, node_id, value)


    # Получение последних данных — возвращает словарь node_id → value для всех тегов, на которые есть подписка.
    def get_latest_data(self) -> Dict[str, Any]:
        """Получение последних данных — возвращает словарь node_id → value для всех тегов, на которые есть подписка."""
        # Используем блокировку, чтобы гарантировать целостность данных при доступе из разных потоков.
        with self._latest_data_lock:
            # Возвращаем копию словаря с последними данными,
            # чтобы внешний код не мог случайно изменить внутреннее состояние потока.
            return self._latest_data.copy()


    # Возвращает текущее состояние подключения к серверу.
    @property
    def is_connected(self) -> bool:
        """
        Свойство is_connected — возвращает текущее состояние подключения к серверу."""
        # Если worker ещё не создан, 
        if self.worker:
            # Если worker существует, возвращает его свойство is_connected,
            # которое должно отражать реальное состояние подключения к серверу.
            return self.worker.is_connected
        # Возвращает внутренний флаг _connected,
        # который устанавливается при успешном подключении и отключении от сервера.
        return self._connected


    # Получение списка всех тегов, на которые в данный момент есть подписка,
    # от AsyncOpcUaWorker — может быть полезно для отображения текущих подписок в интерфейсе или для отладки.
    def get_subscribed_tags(self) -> List[str]:
        """
        Получить список всех тегов, на которые в данный момент есть подписка,
        от AsyncOpcUaWorker — может быть полезно для отображения текущих подписок в интерфейсе или для отладки.
        """
        # Если worker ещё не создан, возвращаем пустой список, чтобы избежать ошибок при попытке доступа к нему до запуска потока.
        if not self.worker:
            return []
        # Если worker существует, вызываем его метод get_subscribed_tags(),
        # который должен возвращать список node_id всех тегов, на которые есть подписка.
        return self.worker.get_subscribed_tags()
    

    # Получение статистики и состояния от AsyncOpcUaWorker — может включать количество подписок,
    # состояние соединения, активные опросы и другую полезную информацию для мониторинга и отладки.
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику и состояние от AsyncOpcUaWorker — может включать количество подписок
        состояние соединения, активные опросы и другую полезную информацию для мониторинга и отладки.
        """
        # Если worker ещё не создан, возвращаем пустой словарь, чтобы избежать ошибок при попытке доступа к нему до запуска потока.
        if not self.worker:
            return {}
        # Если worker существует, вызываем его метод get_stats(),
        # который должен возвращать словарь с полезной информацией о состоянии и статистике работы.
        return self.worker.get_stats()
