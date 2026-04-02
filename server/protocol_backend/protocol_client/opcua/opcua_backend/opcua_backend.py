"""
OpcUaBackend — менеджер нескольких OPC UA серверов.

"""
# Модуль logging — стандартный Python-логгер, используется для вывода info/warning/error сообщений.
import logging
# Dict — словарь с типизированными ключами и значениями.
# Optional — тип, который может быть None или указанным типом.
# Callable — тип для функций/лямбд (callback'ов).
# Any — любой тип значения.
# List — список с типизированными элементами.
from typing import Dict, Optional, Callable, Any, List
# OpcUaWorkerThread — поток, который управляет одним OPC UA соединением.
from protocol_backend.protocol_client.opcua.opcua_thread.opcua_worker_thread import OpcUaWorkerThread

# Создаём логгер для этого модуля — имя берётся из имени файла автоматически.
log = logging.getLogger(__name__)


class OpcUaBackend:
    """
    Управляет пулом OpcUaWorkerThread'ов.
    Внешний API — публичные on_* callbacks:

        backend.on_connected    = lambda srv: ...
        backend.on_data_updated = lambda srv, nid, val: ...
    """

    def __init__(self):
        # Реестр серверов: server_id → {endpoint, namespace, timeout, thread}.
        # Каждый сервер хранит свои параметры подключения и ссылку на worker thread.
        # Ключ — server_id (строка), значение — dict с параметрами и thread.
        self.servers                : Dict[str, dict] = {}
        # Callback: сервер успешно подключился.
        # Аргумент — server_id (str).
        # Назначается снаружи: backend.on_connected = lambda srv: print(srv)
        self.on_connected           : Optional[Callable[[str], None]]           = None
        # Callback: сервер отключился (штатно или по ошибке).
        # Аргумент — server_id (str).
        self.on_disconnected        : Optional[Callable[[str], None]]           = None
        # Callback: ошибка соединения или операции.
        # Аргументы — server_id (str) и текст ошибки (str).
        self.on_connection_error    : Optional[Callable[[str, str], None]]      = None
        # Callback: получено новое значение тега от подписки или poll.
        # Аргументы — server_id (str), node_id (str), value (Any).
        self.on_data_updated        : Optional[Callable[[str, str, Any], None]] = None
        # Callback: сервер подтвердил подписку на тег.
        # Аргументы — server_id (str), node_id (str).
        self.on_tag_subscribed      : Optional[Callable[[str, str], None]]      = None
        # Callback: завершился один цикл poll. Все теги группы с одним timestamp.
        # Аргументы — server_id (str), poll_name (str), batch dict {node_id: value}.
        self.on_poll_batch          : Optional[Callable[[str, str, dict], None]] = None
        # Callback: watchdog обнаружил пропажу связи с сервером.
        # Аргумент — server_id (str).
        self.on_watchdog_disconnect : Optional[Callable[[str], None]]           = None

# Управление серверами


    # Добавить сервер в реестр (без подключения)
    def add_server(self, server_id: str, endpoint: str, namespace: int = 2, timeout: float = 10.0) -> bool:
        """Добавить сервер в конфиг (без подключения).
        Args:
            server_id (str): Уникальный идентификатор сервера, используемый в остальных методах для обращения к этому серверу.
            endpoint (str): URL-адрес OPC UA сервера, например "opc.tcp://localhost:4840"
            namespace (int): Пространство имен OPC UA.
            timeout (float): Таймаут подключения в секундах."""
        # Проверяем, не зарегистрирован ли уже сервер с таким идентификатором.
        if server_id in self.servers:
            # Если сервер уже есть — не перезаписываем, чтобы не сломать активное соединение.
            # Caller должен сначала вызвать remove_server(), а потом add_server() заново.
            return False
        # Сохраняем конфиг сервера в реестр.
        # thread=None — поток будет создан позже при вызове connect_server().
        self.servers[server_id] = {
            "endpoint" : endpoint,   # URL OPC UA сервера
            "namespace": namespace,  # Пространство имён (обычно 2)
            "timeout"  : timeout,    # Таймаут операций в секундах
            "thread"   : None,       # Worker thread — создаётся при connect_server()
        }
        # Возвращаем True — сервер успешно добавлен в реестр.
        return True


    # Удалить сервер из реестра (с отключением если он подключён)
    def remove_server(self, server_id: str, force: bool = False) -> bool:
        """Удалить сервер из реестра.
        Args:
            server_id (str): Идентификатор сервера.
            force (bool): True — отключить и удалить даже если сервер подключён прямо сейчас."""
        # Если сервера с таким id нет в реестре — нечего удалять, возвращаем False.
        if server_id not in self.servers:
            return False
        # Проверяем, подключён ли сервер в данный момент.
        if self.is_connected(server_id):
            # Если force=False — отказываем в удалении подключённого сервера.
            # Это защита от случайного обрыва соединения.
            if not force:
                return False
            # force=True: сначала корректно отключаемся (blocking=True — ждём завершения).
            # Это гарантирует, что поток завершится до удаления записи.
            self.disconnect_server(server_id, blocking=True)
        # Удаляем запись из реестра — освобождаем память и конфиг.
        del self.servers[server_id]
        # Возвращаем True — сервер успешно удалён.
        return True


    # Получить список всех зарегистрированных серверов с их текущим статусом
    def get_servers(self) -> Dict[str, dict]:
        """Вернуть словарь всех серверов: server_id → {endpoint, namespace, connected}."""
        # Строим словарь через dict comprehension — проходим по всем серверам в реестре.
        return {
            # Ключ — server_id, значение — публичные поля (без внутреннего thread).
            sid: {
                "endpoint" : s["endpoint"],           # URL сервера
                "namespace": s["namespace"],           # Пространство имён
                "connected": self.is_connected(sid),  # Текущий статус подключения
            }
            for sid, s in self.servers.items()
        }


    # Проверить, подключён ли сервер прямо сейчас
    def is_connected(self, server_id: str) -> bool:
        """Проверить, подключён ли сервер. Возвращает True только если thread жив и worker подключён."""
        # Ищем сервер в реестре — если не найден, значит не подключён.
        server = self.servers.get(server_id)
        if not server:
            # Сервер не зарегистрирован — точно не подключён.
            return False
        # Получаем worker thread из конфига.
        thread = server.get("thread")
        # Проверяем два условия:
        # 1. Поток существует и жив (is_alive) — значит event loop запущен.
        # 2. Worker внутри потока действительно подключён к серверу (is_connected).
        if thread and thread.is_alive():
            return thread.is_connected
        # Thread не создан или уже завершён — считаем что не подключены.
        return False


# ── Connection ────────────────────────────────────────────────────────────


    # Подключиться к серверу (создаёт новый thread если нужно)
    def connect_server(self, server_id: str) -> bool:
        """Запустить подключение к серверу.
        Args:
            server_id (str): Идентификатор сервера из реестра."""
        # Если сервер не зарегистрирован — подключаться не к чему.
        if server_id not in self.servers:
            return False
        # Если уже подключены — ничего не делаем, считаем успехом.
        if self.is_connected(server_id):
            return True
        # Получаем конфиг сервера из реестра.
        server = self.servers[server_id]
        # Берём текущий thread (может быть None если ещё не создавался).
        thread = server.get("thread")
        # Проверяем, жив ли thread — он может быть создан но уже завершён.
        is_running = thread.is_alive() if thread else False

        if not is_running:
            # Thread не запущен — создаём новый с параметрами из конфига.
            thread = OpcUaWorkerThread(
                server_id = server_id,           # ID для логов и идентификации
                endpoint  = server["endpoint"],  # URL сервера
                namespace = server["namespace"], # Пространство имён
                timeout   = server["timeout"],   # Таймаут операций
            )
            # Подключаем callback'и thread'а к нашим внутренним обработчикам.
            # Это нужно сделать ДО запуска потока, чтобы не пропустить ранние события.
            self._connect_thread_callbacks(server_id, thread)
            # Сохраняем thread в реестр сервера.
            server["thread"] = thread
            # Когда event loop будет готов — сразу инициируем подключение к серверу.
            # on_loop_ready вызывается из потока, как только asyncio loop запущен.
            thread.on_loop_ready = lambda: thread.connect_to_server()
            # Запускаем поток — внутри него создаётся event loop и AsyncOpcUaWorker.
            thread.start()
        else:
            # Thread уже запущен (loop работает) — просто даём команду подключиться.
            # Это бывает при переподключении после обрыва связи.
            thread.connect_to_server()
        # Возвращаем True — подключение инициировано (не означает что уже подключились).
        return True

    # Отключиться от сервера
    def disconnect_server(self, server_id: str, blocking: bool = False) -> bool:
        """Отключиться от сервера.
        Args:
            server_id (str): Идентификатор сервера.
            blocking (bool): True — ждать завершения потока перед возвратом."""
        # Если сервер не зарегистрирован — нечего отключать.
        if server_id not in self.servers:
            return False
        # Если уже не подключены — считаем успехом, ничего делать не нужно.
        if not self.is_connected(server_id):
            return True
        # Останавливаем worker thread — он сам отключится от сервера и завершится.
        self.servers[server_id]["thread"].stop(blocking=blocking)
        return True

    # Подключиться ко всем зарегистрированным серверам
    def connect_all(self):
        """Подключиться ко всем серверам из реестра, которые ещё не подключены."""
        # Проходим по всем зарегистрированным серверам.
        for sid in self.servers:
            # Подключаем только те, которые ещё не подключены — не трогаем активные соединения.
            if not self.is_connected(sid):
                self.connect_server(sid)

    # Отключиться от всех серверов
    def disconnect_all(self, blocking: bool = False):
        """Отключиться от всех серверов.
        Args:
            blocking (bool): True — ждать завершения всех потоков перед возвратом."""
        # Список потоков для ожидания при blocking=True.
        threads = []
        # Проходим по копии ключей — list() защищает от изменения словаря во время итерации.
        for sid in list(self.servers):
            # Получаем конфиг сервера.
            server = self.servers.get(sid)
            # Останавливаем только подключённые серверы.
            if server and self.is_connected(sid):
                # Останавливаем неблокирующе (blocking=False) — все потоки начнут завершаться параллельно.
                server["thread"].stop(blocking=False)
                # Сохраняем ссылку для последующего ожидания.
                threads.append(server["thread"])
        if blocking:
            # Ждём завершения каждого потока (до 2 секунд на каждый).
            for t in threads:
                t.join(2.0)


# ── Read / Write ──────────────────────────────────────────────────────────


    # Читать одно значение узла
    def read_node(self, server_id: str, node_id: str) -> bool:
        """Запросить чтение одного узла. Результат придёт в on_read_completed на thread.
        Args:
            server_id (str): Идентификатор сервера.
            node_id (str): Адрес узла, например "ns=2;s=Temperature"."""
        # Получаем thread только если сервер подключён — иначе операция бессмысленна.
        t = self._get_connected_thread(server_id)
        if not t:
            # Сервер не подключён — возвращаем False.
            return False
        # Передаём команду чтения в event loop потока.
        t.read_node(node_id)
        return True


    # Записать значение в узел
    def write_node(self, server_id: str, node_id: str, value: Any) -> bool:
        """Записать значение в узел. Результат придёт в on_write_completed.
        Args:
            server_id (str): Идентификатор сервера.
            node_id (str): Адрес узла.
            value (Any): Значение для записи — тип должен совпадать с типом узла на сервере."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём команду записи в event loop потока.
        t.write_node(node_id, value)
        return True


    # Читать несколько узлов за один запрос
    def read_multiple_nodes(self, server_id: str, node_ids: List[str]) -> bool:
        """Читать несколько узлов. Результат придёт в on_batch_read_completed в виде dict node_id → value.
        Args:
            server_id (str): Идентификатор сервера.
            node_ids (list): Список адресов узлов для чтения."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём список узлов в event loop — они будут прочитаны параллельно.
        t.read_multiple_nodes(node_ids)
        return True


    # Записать несколько значений за один запрос
    def write_multiple_nodes(self, server_id: str, values: Dict[str, Any]) -> bool:
        """Записать несколько значений. Результат придёт в on_batch_write_completed в виде dict node_id → success.
        Args:
            server_id (str): Идентификатор сервера.
            values (dict): Словарь node_id → value для записи."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём словарь значений в event loop — они будут записаны параллельно.
        t.write_multiple_nodes(values)
        return True


 # ── Subscriptions ─────────────────────────────────────────────────────────


    # Подписаться на изменения одного тега
    def subscribe_tag(self, server_id: str, node_id: str, tag_name: Optional[str] = None) -> bool:
        """Подписаться на изменения тега. При каждом изменении будет вызван on_data_updated.
        Args:
            server_id (str): Идентификатор сервера.
            node_id (str): Адрес узла.
            tag_name (str | None): Человекочитаемое имя тега для логов (необязательно)."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём команду подписки в event loop потока.
        t.subscribe_tag(node_id, tag_name)
        return True


    # Отписаться от изменений тега
    def unsubscribe_tag(self, server_id: str, node_id: str) -> bool:
        """Отписаться от изменений тега.
        Args:
            server_id (str): Идентификатор сервера.
            node_id (str): Адрес узла."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём команду отписки в event loop потока.
        t.unsubscribe_tag(node_id)
        return True


    # Подписаться на несколько тегов одновременно
    def subscribe_multiple_tags(self, server_id: str, tags: Dict[str, str]) -> bool:
        """Подписаться на несколько тегов: {node_id: tag_name}.
        Args:
            server_id (str): Идентификатор сервера.
            tags (dict): Словарь node_id → tag_name."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём словарь тегов в event loop — подписки создаются параллельно.
        t.subscribe_multiple_tags(tags)
        return True


    # Получить список всех активных подписок
    def get_subscribed_tags(self, server_id: str) -> List[str]:
        """Вернуть список node_id всех активных подписок на сервере."""
        # Используем _get_thread (не _get_connected_thread) — можно читать даже без подключения.
        t = self._get_thread(server_id)
        # Если thread есть — делегируем, иначе возвращаем пустой список.
        return t.get_subscribed_tags() if t else []


# ── Polling ───────────────────────────────────────────────────────────────


    # Запустить именованный циклический опрос группы тегов
    def start_polling(self, server_id: str, name: str, node_ids: List[str],
                      interval: float = 1.0, sequential: bool = False) -> bool:
        """Запустить именованный poll — периодически читать группу тегов.
        Args:
            server_id (str): Идентификатор сервера.
            name (str): Имя группы опроса (используется в stop_polling для остановки).
            node_ids (list): Список node_id для опроса.
            interval (float): Интервал опроса в секундах.
            sequential (bool): True — читать теги последовательно, False — параллельно."""
        # Получаем thread только если сервер подключён.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Запускаем poll в event loop потока.
        t.start_polling(name, node_ids, interval, sequential)
        return True


    # Остановить циклический опрос по имени
    def stop_polling(self, server_id: str, name: Optional[str] = None) -> bool:
        """Остановить poll по имени. None — остановить все активные polls.
        Args:
            server_id (str): Идентификатор сервера.
            name (str | None): Имя группы опроса или None для остановки всех."""
        # Используем _get_thread — можно остановить poll даже без активного соединения.
        t = self._get_thread(server_id)
        if not t:
            return False
        # Передаём команду остановки в event loop.
        t.stop_polling(name)
        return True


    # Получить список всех активных polls
    def get_active_polls(self, server_id: str) -> Dict[str, Dict]:
        """Вернуть dict активных polls: name → {node_ids, interval, ...}."""
        # Используем _get_thread — можно читать метаданные даже без активного соединения.
        t = self._get_thread(server_id)
        # Если thread есть — делегируем, иначе возвращаем пустой dict.
        return t.get_active_polls() if t else {}
    

# ── Watchdog ──────────────────────────────────────────────────────────────


    # Запустить watchdog — периодическую проверку связи с сервером
    def start_watchdog(self, server_id: str, interval: float = 5.0) -> bool:
        """Запустить watchdog — он будет периодически проверять связь с сервером.
        При потере связи вызовет on_watchdog_disconnect.
        Args:
            server_id (str): Идентификатор сервера.
            interval (float): Интервал проверки в секундах."""
        # Watchdog имеет смысл только при активном подключении.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Запускаем watchdog в event loop потока.
        t.start_watchdog(interval)
        return True


    # Остановить watchdog
    def stop_watchdog(self, server_id: str) -> bool:
        """Остановить watchdog для указанного сервера."""
        # Используем _get_thread — можно остановить watchdog даже если уже отключились.
        t = self._get_thread(server_id)
        if not t:
            return False
        # Передаём команду остановки в event loop.
        t.stop_watchdog()
        return True


    # Проверить, активен ли watchdog прямо сейчас
    def is_watchdog_active(self, server_id: str) -> bool:
        """Вернуть True если watchdog запущен для данного сервера."""
        # Используем _get_thread — читаем свойство напрямую без проверки подключения.
        t = self._get_thread(server_id)
        # Если thread есть — читаем его свойство, иначе False.
        return t.is_watchdog_active if t else False


# ── Exploration ───────────────────────────────────────────────────────────


    # Обойти дерево узлов сервера
    def browse_nodes(self, server_id: str, start_node_id: Optional[str] = None, depth: int = 1) -> bool:
        """Обойти дерево узлов. Результат придёт в on_browse_completed.
        Args:
            server_id (str): Идентификатор сервера.
            start_node_id (str | None): Начальный узел обхода. None — корень сервера.
            depth (int): Глубина обхода дерева (1 — только прямые дочерние узлы)."""
        # Для обхода нужно активное соединение.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём команду обхода в event loop потока.
        t.browse_nodes(start_node_id, depth)
        return True


    # Читать метаданные узла
    def read_node_info(self, server_id: str, node_id: str) -> bool:
        """Прочитать метаданные узла (тип данных, описание, атрибуты). Результат придёт в on_node_info_completed.
        Args:
            server_id (str): Идентификатор сервера.
            node_id (str): Адрес узла."""
        # Для чтения метаданных нужно активное соединение.
        t = self._get_connected_thread(server_id)
        if not t:
            return False
        # Передаём команду чтения метаданных в event loop потока.
        t.read_node_info(node_id)
        return True


# ── Data access ───────────────────────────────────────────────────────────


    # Получить последние известные значения тегов одного сервера
    def get_latest_data(self, server_id: str) -> Dict[str, Any]:
        """Вернуть последние полученные значения тегов: node_id → value.
        Возвращает кэшированные данные — не делает запрос к серверу."""
        # Используем _get_thread — данные доступны даже без активного соединения.
        t = self._get_thread(server_id)
        # Если thread есть — берём кэш данных, иначе пустой dict.
        return t.get_latest_data() if t else {}


    # Получить последние значения тегов всех серверов
    def get_all_data(self) -> Dict[str, Dict[str, Any]]:
        """Вернуть данные всех серверов: server_id → {node_id → value}."""
        # Собираем данные по всем зарегистрированным серверам через get_latest_data().
        return {sid: self.get_latest_data(sid) for sid in self.servers}


    # Получить статистику работы worker'а
    def get_stats(self, server_id: str) -> Dict[str, Any]:
        """Вернуть статистику работы worker'а: uptime, время операций чтения/записи и т.д."""
        # Используем _get_thread — статистика доступна даже без активного соединения.
        t = self._get_thread(server_id)
        # Если thread есть — берём статистику, иначе пустой dict.
        return t.get_stats() if t else {}


 # ── Lifecycle ─────────────────────────────────────────────────────────────


    # Полная остановка — отключить всё и очистить реестр
    def stop_all(self):
        """Отключить все серверы и очистить реестр. Вызывается при завершении работы приложения."""
        # Отключаемся от всех серверов и ждём завершения потоков (blocking=True).
        self.disconnect_all(blocking = True)
        # Очищаем реестр — освобождаем память.
        self.servers.clear()


# ── Internal ──────────────────────────────────────────────────────────────


    # Получить thread сервера (без проверки подключения)
    def _get_thread(self, server_id: str) -> Optional[OpcUaWorkerThread]:
        """Вернуть thread сервера или None если сервер не зарегистрирован.
        Не проверяет подключение — используется для операций, которые работают и без него."""
        # Ищем сервер в реестре.
        server = self.servers.get(server_id)
        # Если сервер есть — возвращаем thread (может быть None если не запускался).
        return server.get("thread") if server else None


    # Получить thread только если сервер подключён
    def _get_connected_thread(self, server_id: str) -> Optional[OpcUaWorkerThread]:
        """Вернуть thread сервера или None если сервер не подключён.
        Используется во всех операциях, которые требуют активного соединения с сервером."""
        # Проверяем подключение — если нет, возвращаем None.
        if not self.is_connected(server_id):
            return None
        # Сервер подключён — возвращаем его thread напрямую из реестра.
        return self.servers[server_id]["thread"]


    # Подключить обработчики событий thread'а к публичным callback'ам backend'а
    def _connect_thread_callbacks(self, server_id: str, thread: OpcUaWorkerThread):
        """Подключить обработчики событий из worker thread к публичным callback'ам backend.
        Args:
            server_id (str): Идентификатор сервера, для которого настраиваются callbacks.
            thread (OpcUaWorkerThread): Экземпляр worker thread, для которого настраиваются callbacks."""
        # Подключаем on_connected — при успешном подключении к серверу.
        # lambda добавляет server_id, которого нет в сигнатуре thread callback'а.
        thread.on_connected           = lambda: self._on_server_connected(server_id)
        # Подключаем on_disconnected — при отключении от сервера (штатном или аварийном).
        thread.on_disconnected        = lambda: self._on_server_disconnected(server_id)
        # Подключаем on_connection_error — при ошибке соединения или операции.
        # err — текст ошибки из исключения.
        thread.on_connection_error    = lambda err: self._on_server_error(server_id, err)
        # Подключаем on_data_updated — при получении нового значения тега.
        # nid — node_id тега, val — новое значение.
        thread.on_data_updated        = lambda nid, val: self._on_data_updated(server_id, nid, val)
        # Подключаем on_tag_subscribed — когда сервер подтвердил подписку на тег.
        # nid — node_id тега.
        thread.on_tag_subscribed      = lambda nid: self._on_tag_subscribed(server_id, nid)
        # Подключаем on_watchdog_disconnect — когда watchdog обнаружил потерю связи.
        thread.on_poll_batch          = lambda name, batch: self._on_poll_batch(server_id, name, batch)
        thread.on_watchdog_disconnect = lambda: self._on_watchdog_disconnect(server_id)


    # Обработчик успешного подключения к серверу
    def _on_server_connected(self, server_id: str):
        """Вызывается из worker thread при успешном подключении к серверу.
        Args:
            server_id (str): Идентификатор сервера, к которому произошло подключение."""
        # Логируем подключение — полезно при отладке и мониторинге.
        log.info("Connected: %s", server_id)
        # Если внешний callback назначен — вызываем его с server_id.
        if self.on_connected:
            self.on_connected(server_id)


    # Обработчик отключения от сервера
    def _on_server_disconnected(self, server_id: str):
        """Вызывается из worker thread при отключении от сервера.
        Args:
            server_id (str): Идентификатор сервера, от которого произошло отключение."""
        # Логируем отключение с уровнем WARNING — это нештатная ситуация.
        log.warning("Disconnected: %s", server_id)
        # Если внешний callback назначен — уведомляем внешний код.
        if self.on_disconnected:
            self.on_disconnected(server_id)


    # Обработчик ошибок соединения
    def _on_server_error(self, server_id: str, error: str):
        """Вызывается из worker thread при ошибке соединения или операции.
        Args:
            server_id (str): Идентификатор сервера, для которого произошла ошибка.
            error (str): Текст ошибки."""
        # Логируем ошибку с уровнем ERROR — важно для диагностики.
        log.error("Error [%s]: %s", server_id, error)
        # Если внешний callback назначен — передаём server_id и текст ошибки.
        if self.on_connection_error:
            self.on_connection_error(server_id, error)


    # Обработчик получения нового значения тега
    def _on_data_updated(self, server_id: str, node_id: str, value: Any):
        """Вызывается из worker thread при получении нового значения тега.
        Args:
            server_id (str): Идентификатор сервера, от которого пришли данные.
            node_id (str): Адрес узла, значение которого изменилось.
            value (Any): Новое значение."""
        # Если внешний callback назначен — передаём все три параметра.
        if self.on_data_updated:
            self.on_data_updated(server_id, node_id, value)


    # Обработчик завершения poll-цикла (батч всех тегов группы)
    def _on_poll_batch(self, server_id: str, name: str, batch: dict):
        if self.on_poll_batch:
            self.on_poll_batch(server_id, name, batch)


    # Обработчик успешной подписки на тег
    def _on_tag_subscribed(self, server_id: str, node_id: str):
        """Вызывается из worker thread когда сервер подтвердил подписку на тег.
        Args:
            server_id (str): Идентификатор сервера.
            node_id (str): Адрес узла, на который оформлена подписка."""
        # Если внешний callback назначен — уведомляем внешний код.
        if self.on_tag_subscribed:
            self.on_tag_subscribed(server_id, node_id)


    # Обработчик срабатывания watchdog
    def _on_watchdog_disconnect(self, server_id: str):
        """Вызывается из worker thread когда watchdog обнаружил потерю связи с сервером.
        Args:
            server_id (str): Идентификатор сервера, для которого сработал watchdog."""
        # Если внешний callback назначен — уведомляем внешний код о потере связи.
        if self.on_watchdog_disconnect:
            self.on_watchdog_disconnect(server_id)
