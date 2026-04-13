import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Callable
from asyncua import Client, Node
from asyncua.common.subscription import Subscription, DataChangeNotif
from .opcua_security_mixin import SecurityMixin
from .opcua_lifecycle_mixin import LifecycleMixin
from .opcua_exploration_mixin import ExplorationMixin
from .opcua_config_mixin import ConfigMixin

logger = logging.getLogger(__name__)

# Обработчик изменений данных от OPC UA подписок.
# Это класс-адаптер между интерфейсом библиотеки asyncua и нашим кодом.
# asyncua при создании подписки (create_subscription) принимает объект handler,
# у которого ОБЯЗАТЕЛЬНО должен быть метод datachange_notification().
# Когда значение переменной на OPC UA сервере изменяется, asyncua автоматически
# вызывает handler.datachange_notification(node, val, data).
#
# Цепочка вызовов:
#   OPC UA Сервер → asyncua библиотека → SubscriptionHandler.datachange_notification()
#   → self.callback(node_id, val) → AsyncOpcUaWorker._on_data_change()
#   → OpcUaWorkerThread (QThread) → Qt signal → GUI
class SubscriptionHandler:
    """
    SubscriptionHandler — паттерн Observer (наблюдатель) для OPC UA протокола.

    Библиотека asyncua требует объект-обработчик с методом datachange_notification(),
    который она будет вызывать при изменении данных на сервере.
    Этот класс оборачивает вызов asyncua в простой callback(node_id, value).
    """

    def __init__(self, callback: Optional[Callable[[str, Any], None]] = None):
        """
        Args:
            callback: Функция-обработчик изменений данных.
                Тип: Optional[Callable[[str, Any], None]]
                Разбор типа по частям:
                  - Optional[...]  — может быть None (callback необязателен)
                  - Callable       — вызываемый объект (функция, метод, lambda)
                  - [str, Any]     — принимает 2 аргумента:
                      str — node_id, строковый ID узла (например "ns=2;s=Temperature")
                      Any — value, новое значение (float, int, bool, str — зависит от узла)
                  - None           — ничего не возвращает (return type)
                  - = None         — значение по умолчанию: обработчик не задан

                Примеры того, что можно передать:
                  callback=lambda nid, val: print(nid, val)
                  callback=self._on_data_change
                  callback=None  (изменения будут молча игнорироваться)
        """

        # Сохраняем переданную callback-функцию как поле экземпляра.
        # При вызове datachange_notification() мы проверим self.callback на None
        # и если он задан — вызовем его с преобразованными аргументами.
        self.callback = callback

    def datachange_notification(self, node: Node, val, data: DataChangeNotif):
        """
        Вызывается АВТОМАТИЧЕСКИ библиотекой asyncua при изменении значения переменной.
        Мы НЕ вызываем этот метод сами — его вызывает asyncua изнутри.

        Args:
            node (Node): Объект узла OPC UA, значение которого изменилось.
                Содержит:
                  node.nodeid                    — объект NodeId (адрес на сервере)
                  node.nodeid.NamespaceIndex     — namespace (например 2)
                  node.nodeid.Identifier         — имя переменной ("Temperature")
                  str(node.nodeid)               — строка "ns=2;s=Temperature"

            val: Новое значение переменной. Тип зависит от переменной на сервере:
                float  — температура, давление (24.1, 101.3)
                int    — счётчики, коды (1500, 42)
                bool   — состояния (True/False)
                str    — текстовые статусы ("Running")

            data (DataChangeNotif): Полная структура уведомления от сервера.
                Содержит (не используется в текущем коде, но доступно):
                  data.monitored_item.Value.SourceTimestamp  — когда PLC зафиксировал значение
                  data.monitored_item.Value.ServerTimestamp  — когда OPC сервер отправил
                  data.monitored_item.Value.StatusCode       — качество данных (Good/Bad)
        """

        # Преобразуем объект NodeId в строку для удобства.
        # NodeId(ns=2, s="Temperature") → "ns=2;s=Temperature"
        node_id = str(node.nodeid)

        # Проверяем что callback задан (не None) и вызываем его.
        # Передаём только node_id и val — упрощённый интерфейс.
        # Если нужен timestamp или quality — можно расширить callback, добавив параметр data.
        if self.callback:
            self.callback(node_id, val)


# Асинхронный OPC UA клиент
class AsyncOpcUaWorker(SecurityMixin, LifecycleMixin, ExplorationMixin, ConfigMixin):
    def __init__(
        self,
        endpoint                : str,
        namespace               : int = 2,
        timeout                 : float = 10.0,
        on_data_changed         : Optional[Callable[[str, Any], None]] = None,
        username                : Optional[str] = None,
        password                : Optional[str] = None,
        certificate_path        : Optional[str] = None,
        private_key_path        : Optional[str] = None,
        security_policy         : Optional[str] = None,
        security_mode           : Optional[str] = None,
        auto_reconnect          : bool = False,
        reconnect_interval      : float = 5.0,
        max_reconnect_attempts  : int = 0):
        """
        Args:
            endpoint: URL сервера (например "opc.tcp://192.168.1.10:4840")
            namespace: Namespace index (по умолчанию 2)
            timeout: Таймаут операций в секундах
            on_data_changed: Callback для изменений (node_id, value)
            username: Имя пользователя для аутентификации (None = анонимный доступ)
            password: Пароль для аутентификации
            certificate_path: Путь к файлу клиентского сертификата X.509 (.der или .pem).
                None = без сертификата (анонимный или username/password доступ).
                Пример: "certs/client_cert.der"
            private_key_path: Путь к файлу закрытого ключа клиента (.pem).
                Используется вместе с certificate_path для подписи сообщений.
                Пример: "certs/client_key.pem"
            security_policy: Политика безопасности для шифрования канала.
                None = "None" (без шифрования, подходит для тестов).
                Варианты:
                  "Basic256Sha256" — рекомендуемая (AES-256 + SHA-256)
                  "Basic256"       — устаревшая (AES-256 + SHA-1)
                  "Basic128Rsa15"  — устаревшая (RSA 1.5, не рекомендуется)
                  "Aes128Sha256RsaOaep" — новая (AES-128 + SHA-256 + RSA OAEP)
            security_mode: Режим безопасности сообщений.
                None = "None" (без подписи и шифрования).
                Варианты:
                  "Sign"           — сообщения подписываются (целостность)
                  "SignAndEncrypt" — подпись + шифрование (конфиденциальность + целостность)
            auto_reconnect: Включить автоматическое переподключение при обрыве
            reconnect_interval: Интервал между попытками переподключения (секунды)
            max_reconnect_attempts: Макс. число попыток (0 = бесконечно)
        """
        # Сохраняем параметры подключения к OPC UA серверу
        self.endpoint = endpoint
        self.namespace = namespace
        self.timeout = timeout
        self.on_data_changed = on_data_changed
        self.on_poll_batch: Optional[Callable[[str, dict], None]] = None

        # --- Security ---
        # Логин/пароль для аутентификации на сервере. None = анонимный доступ.
        self._username = username
        self._password = password

        # --- Certificate (X.509) ---
        # Сертификат и ключ для TLS-аутентификации и шифрования канала.
        self._certificate_path = certificate_path
        self._private_key_path = private_key_path

        # Политика безопасности — определяет алгоритмы шифрования канала.
        self._security_policy = security_policy

        # Режим безопасности — определяет что защищается.
        self._security_mode = security_mode

        # Создаем контейнеры до подключения:
        # - Объекты asyncua
        self.client: Optional[Client] = None
        # - Подписки
        self.subscription: Optional[Subscription] = None
        # - Для вызова datachange_notification()
        self.handler: Optional[SubscriptionHandler] = None
        # - Подписанные теги: {"ns=2;s=Temperature": handle_id}
        self.subscribed_tags: Dict[str, int] = {}
        # - Кэш последних значений: {"ns=2;s=Temperature": 24.1}
        self.latest_data: Dict[str, Any] = {}
        # - Флаг подключения. Приватный (с _) — доступ через property is_connected
        self._connected = False

        # --- Polling (множественные именованные циклы) ---
        # Реестр активных poll loop'ов. Каждый цикл — отдельная запись в словаре.
        # {
        #     "fast": {"task": asyncio.Task, "nodes": [...], "interval": 0.2, "active": True},
        #     "slow": {"task": asyncio.Task, "nodes": [...], "interval": 5.0, "active": True},
        # }
        self._poll_loops: Dict[str, Dict[str, Any]] = {}

        # --- Auto-reconnect ---
        self._auto_reconnect = auto_reconnect
        self._reconnect_interval = reconnect_interval
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_task: Optional[asyncio.Task] = None
        # Сохранённые параметры для восстановления после reconnect
        self._saved_subscriptions: Dict[str, Optional[str]] = {}
        self._saved_polls: Dict[str, Dict[str, Any]] = {}

        # --- Node Cache ---
        # Кэш объектов Node — избегаем повторных вызовов client.get_node().
        # get_node() каждый раз создаёт новый объект Node (парсинг строки node_id).
        # Для hot path (poll loops, частые read/write) это лишние аллокации.
        self._node_cache: Dict[str, Node] = {}

        # Кэш типов для записи: {node_id: type}
        # Заполняется при первой записи — читает текущий тип узла с сервера,
        # чтобы не получать BadTypeMismatch при несовпадении Python-типов.
        self._write_type_cache: Dict[str, type] = {}

        # --- Connection Watchdog ---
        self._watchdog_task: Optional[asyncio.Task] = None
        self._watchdog_interval: float = 5.0

        # --- Diagnostics / Stats ---
        self._stats: Dict[str, Any] = {
            "reads": 0,
            "writes": 0,
            "read_errors": 0,
            "write_errors": 0,
            "reconnects": 0,
            "last_read_ms": 0.0,
            "last_write_ms": 0.0,
            "connected_at": None,
            "total_uptime_s": 0.0,
        }


# Подключение к серверу
    async def connect(self) -> bool:
        """
        Подключение к OPC UA серверу.
        Returns:
         - True при успехе.
         - При ошибке ConnectionError.
        """
        try:
            # Если уже есть старый клиент — закрываем его перед созданием нового.
            # Иначе его внутренние задачи (_monitor_server_loop, _renew_channel_loop)
            # останутся жить в фоне и будут генерировать "Error while renewing session".
            if self.client is not None:
                old = self.client
                self.client = None
                self._node_cache.clear()
                self._write_type_cache.clear()
                try:
                    await asyncio.wait_for(old.disconnect(), timeout=5.0)
                except Exception:
                    pass

            # Создаём объект Client
                # - url — адрес сервера ("opc.tcp://192.168.1.10:4840")
                # - timeout — сколько ждать ответа от сервера (секунды)
            self.client = Client(url = self.endpoint, timeout = self.timeout)

            # Аутентификация устанавливаются ПЕРЕД connect(), иначе не будут применены.
            if self._username and self._password:
                self.client.set_user(self._username)
                self.client.set_password(self._password)

            # --- Security: сертификат X.509 ---
            # Если указаны сертификат и ключ — настраиваем TLS-безопасность канала.
            # ВАЖНО: вызывать ПЕРЕД connect(), иначе соединение установится без шифрования.
            if self._certificate_path and self._private_key_path:
                await self._apply_certificate_security()

            # Устанавливаем TCP соединение с сервером.
            await self.client.connect()
            # Создаём обработчик уведомлений (наш SubscriptionHandler).
            self.handler = SubscriptionHandler(callback = self._on_data_change)

            # Создаём подписку без тегов (Subscription) на сервере.
            self.subscription = await self.client.create_subscription(
                period = 500,
                handler = self.handler)
            # Флаг подключения = True.
            self._connected = True
            # Записываем время подключения для статистики uptime
            self._stats["connected_at"] = datetime.now(timezone.utc)
            return True
        # Обработка исключений
        except Exception as e:
            import traceback
            logger.error(f"Connect failed (full traceback):\n{traceback.format_exc()}")
            self._connected = False
            raise ConnectionError(f"Failed to connect to {self.endpoint}: {e}")


# Отключение от сервера
    async def disconnect(self) -> bool:
        """
        Отключение от OPC UA сервера.
        Returns:
         - True при успехе.
         - При ошибке RuntimeError.
        """
        try:
            # Останавливаем watchdog — соединение закрывается намеренно
            await self.stop_watchdog()
            # Останавливаем reconnect если запущен — мы отключаемся намеренно
            await self.stop_reconnect()
            # Останавливаем ВСЕ poll loop'ы — нет смысла опрашивать отключённый сервер
            if self._poll_loops:
                await self.stop_polling()
            # Удаляем подписку на сервере
            if self.subscription:
                await self.subscription.delete()
                self.subscription = None
            # Закрываем соединение с сервером.
            if self.client:
                await self.client.disconnect()
                self.client = None
            # Обновляем статистику uptime перед сбросом флага
            if self._stats["connected_at"]:
                elapsed = (datetime.now(timezone.utc) - self._stats["connected_at"]).total_seconds()
                self._stats["total_uptime_s"] += elapsed
                self._stats["connected_at"] = None
            self._connected = False
            # Очищаем реестр тегов (handle'ы больше не валидны)
            self.subscribed_tags.clear()
            # Очищаем кэш Node-объектов — они привязаны к старому Client
            self._node_cache.clear()
            self._write_type_cache.clear()
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to disconnect: {e}")

    @property
    def is_connected(self) -> bool:
        """
        Проверка подключения к серверу.

        @property — позволяет вызывать как атрибут: worker.is_connected (без скобок).
        Двойная проверка:
          - self._connected  — наш флаг (устанавливается в connect/disconnect)
          - self.client is not None — объект Client существует
        Обе проверки нужны на случай если client был удалён, но флаг не сброшен.
        """
        return self._connected and self.client is not None


# ==================== Security — см. opcua_security_mixin.py ====================

# ==================== Certificate — см. opcua_security_mixin.py ====================

# Однократное чтение ОДНОГО тэга
    async def read_node(self, node_id: str) -> Optional[Any]:
        """
        Однократное чтение значения переменной с OPC UA сервера.
        Args:
            node_id: Строковый адрес узла на сервере.
                Формат: "ns=<namespace>;s=<имя>" или "ns=<namespace>;i=<число>"
        Returns:
            Значение переменной (float, int, bool, str и т.д.)
        Raises:
            ConnectionError: Если не подключены к серверу.
            RuntimeError: Если узел не найден или ошибка чтения.
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")
        try:
            node = self._get_cached_node(node_id)
            t0 = time.perf_counter()
            value = await node.read_value()
            self._stats["reads"] += 1
            self._stats["last_read_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self.latest_data[node_id] = value
            return value
        except Exception as e:
            self._stats["read_errors"] += 1
            raise RuntimeError(f"Failed to read node {node_id}: {e}")


# Однократная запись ОДНОГО тэга
    async def write_node(self, node_id: str, value: Any) -> bool:
        """
        Однократная запись значения в переменную на OPC UA сервере.

        Args:
            node_id: Адрес узла ("ns=2;s=SetPoint", "ns=2;i=1001")
            value: Значение для записи. Тип должен совпадать с типом на сервере:
                float, int, bool, str.
        Returns:
            True при успешной записи.
        Raises:
            ConnectionError: Не подключены к серверу.
            RuntimeError: Узел не найден, нет прав записи, неверный тип значения.
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")

        try:
            node = self._get_cached_node(node_id)
            # При первой записи читаем текущий тип узла с сервера и кэшируем.
            # Это нужно чтобы избежать BadTypeMismatch: OPC UA требует точного совпадения
            # типа (Int16, Bool, Float и т.д.), а Python не знает об этом заранее.
            if node_id not in self._write_type_cache:
                current = await node.read_value()
                if current is not None:
                    self._write_type_cache[node_id] = type(current)
            if node_id in self._write_type_cache:
                typed_value = self._write_type_cache[node_id](value)
            else:
                typed_value = value
            t0 = time.perf_counter()
            await node.write_value(typed_value)
            self._stats["writes"] += 1
            self._stats["last_write_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            return True
        except Exception as e:
            self._stats["write_errors"] += 1
            raise RuntimeError(f"Failed to write node {node_id}: {e}")


# Однократная запись НЕСКОЛЬКИХ тэгов (ПАРАЛЛЕЛЬНО)
    async def write_multiple_nodes(self, values: Dict[str, Any]) -> Dict[str, bool]:
        """
        Пакетная запись нескольких переменных ПАРАЛЛЕЛЬНО через asyncio.gather().

        При ошибке одного тега — остальные всё равно записываются.

        Args:
            values: Словарь {node_id: value} для записи.

        Returns:
            Словарь {node_id: success} — результат по каждому тегу.

        Raises:
            ConnectionError: Не подключены к серверу.
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")

        node_ids = list(values.keys())
        raw_results = await asyncio.gather(
            *[self.write_node(node_id, value) for node_id, value in values.items()],
            return_exceptions=True
        )

        results = {}
        for node_id, result in zip(node_ids, raw_results):
            if isinstance(result, Exception):
                results[node_id] = False
                logger.error(f"Error writing {node_id}: {result}")
            else:
                results[node_id] = True
        return results


# Однократное чтение НЕСКОЛЬКИХ тэгов (ПАРАЛЛЕЛЬНО)
    async def read_multiple_nodes(self, node_ids: List[str]) -> Dict[str, Any]:
        """
        Пакетное чтение нескольких переменных ПАРАЛЛЕЛЬНО через asyncio.gather().

        Все запросы отправляются одновременно — время = макс(время одного запроса),
        а не сумма всех. Для 10 тегов по 20мс: 20мс вместо 200мс.

        При ошибке одного тега — остальные всё равно читаются (return_exceptions=True).

        Args:
            node_ids: Список адресов узлов.

        Returns:
            Словарь {node_id: value} для ВСЕХ запрошенных тегов.
            Если тег не прочитан — его значение будет None.

        Raises:
            ConnectionError: Не подключены к серверу (проверка ДО цикла).
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to OPC UA server")

        nodes = [self._get_cached_node(nid) for nid in node_ids]
        try:
            raw_results = await self.client.read_values(nodes)
        except Exception as e:
            logger.error(f"Batch read error: {e}")
            return {nid: None for nid in node_ids}

        results = {}
        for node_id, result in zip(node_ids, raw_results):
            if isinstance(result, Exception):
                results[node_id] = None
                logger.error(f"Error reading {node_id}: {result}")
            else:
                self.latest_data[node_id] = result
                results[node_id] = result
        return results


# Подписка на тег
    async def subscribe_tag(self, node_id: str, tag_name: Optional[str] = None) -> bool:
        """
        Подписаться на автоматическое отслеживание изменений тега (push-модель).
        Args:
            node_id: Адрес узла ("ns=2;s=Temperature", "ns=2;i=1001")
            tag_name: Человекочитаемое имя тега (опционально).
        Returns:
            True если подписка создана или тег уже был подписан.
        Raises:
            ConnectionError: Не подключены или Subscription не создана.
            RuntimeError: Узел не найден на сервере.
        """
        if not self.is_connected or not self.subscription:
            raise ConnectionError("Not connected or subscription not created")
        if node_id in self.subscribed_tags:
            return True

        try:
            node = self.client.get_node(node_id)
            handle = await self.subscription.subscribe_data_change(node)
            self.subscribed_tags[node_id] = handle
            if tag_name:
                self.latest_data[f"{node_id}_name"] = tag_name
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to subscribe to {node_id}: {e}")


# Отписка от тега
    async def unsubscribe_tag(self, node_id: str) -> bool:
        """
        Отписаться от автоматического отслеживания тега.
        Args:
            node_id: Адрес узла ("ns=2;s=Temperature")
        Returns:
            True если отписка выполнена или тег уже не был подписан.
        Raises:
            RuntimeError: Ошибка при отписке на стороне сервера.
        """
        if node_id not in self.subscribed_tags:
            return True

        try:
            handle = self.subscribed_tags[node_id]
            await self.subscription.unsubscribe(handle)
            del self.subscribed_tags[node_id]
            if node_id in self.latest_data:
                del self.latest_data[node_id]
            name_key = f"{node_id}_name"
            if name_key in self.latest_data:
                del self.latest_data[name_key]
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to unsubscribe from {node_id}: {e}")


# Подписка на несколько тегов (ПАРАЛЛЕЛЬНО)
    async def subscribe_multiple_tags(self, tags: Dict[str, str]) -> Dict[str, bool]:
        """
        Пакетная подписка на несколько тегов ПАРАЛЛЕЛЬНО через asyncio.gather().

        Args:
            tags: Словарь {tag_name: node_id}
                Пример: {
                    "Temperature": "ns=2;s=Temperature",
                    "Pressure":    "ns=2;s=Pressure",
                    "Level":       "ns=2;s=Level"
                }
        Returns:
            Словарь {tag_name: success} — результат по каждому тегу.
            Пример: {"Temperature": True, "Pressure": True, "Level": False}
        """
        tag_names = list(tags.keys())

        # Подписываемся ПАРАЛЛЕЛЬНО — все запросы к серверу одновременно
        raw_results = await asyncio.gather(
            *[self.subscribe_tag(node_id, tag_name)
              for tag_name, node_id in tags.items()],
            return_exceptions=True
        )

        results = {}
        for tag_name, result in zip(tag_names, raw_results):
            if isinstance(result, Exception):
                results[tag_name] = False
                logger.error(f"Error subscribing to {tag_name}: {result}")
            else:
                results[tag_name] = True
        return results


# Получение всех подписок на теги
    def get_subscribed_tags(self) -> List[str]:
        """Получить список подписанных тегов"""
        return list(self.subscribed_tags.keys())


# Сохранение данных в кэш
    def _on_data_change(self, node_id: str, value: Any):
        """
        Промежуточное звено: сохраняет данные в кэш
        и пробрасывает дальше через пользовательский callback.
        Args:
            node_id: Строковый адрес узла, значение которого изменилось.
            value: Новое значение переменной (float, int, bool, str).
        """
        self.latest_data[node_id] = value
        if self.on_data_changed:
            self.on_data_changed(node_id, value)


# Получение последних данных из кэша (без обращения к серверу)
    def get_latest_data(self) -> Dict[str, Any]:
        """
        Получить снимок (snapshot) всех кэшированных значений.
        Returns:
            Копия словаря latest_data: {node_id: последнее_значение}
        """
        return self.latest_data.copy()


# ==================== Node Cache ==========================================

    def _get_cached_node(self, node_id: str) -> Node:
        """
        Получить объект Node из кэша или создать и закэшировать.

        Используется внутренне вместо client.get_node() во всех методах
        read/write для избежания повторного парсинга строки node_id.

        Args:
            node_id: Строковый адрес узла ("ns=2;s=Temperature")

        Returns:
            Node — объект-указатель на узел OPC UA сервера.
        """
        if self.client is None:
            raise ConnectionError("Not connected to OPC UA server")
        if node_id not in self._node_cache:
            self._node_cache[node_id] = self.client.get_node(node_id)
        return self._node_cache[node_id]

    def clear_node_cache(self) -> None:
        """
        Очистить кэш Node-объектов.

        Полезно если структура сервера изменилась (узлы добавлены/удалены).
        При disconnect() кэш очищается автоматически.
        """
        count = len(self._node_cache)
        self._node_cache.clear()
        logger.info(f"Node cache cleared ({count} entries)")

    def get_node_cache_size(self) -> int:
        """Получить количество закэшированных Node-объектов."""
        return len(self._node_cache)

    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику работы клиента.

        Returns:
            Словарь со счётчиками:
            {
                "reads": 1500,            # успешных чтений
                "writes": 42,             # успешных записей
                "read_errors": 3,         # ошибок чтения
                "write_errors": 0,        # ошибок записи
                "reconnects": 1,          # переподключений
                "last_read_ms": 12.5,     # latency последнего чтения
                "last_write_ms": 8.3,     # latency последней записи
                "connected_at": datetime, # когда подключились
                "total_uptime_s": 3600.0, # общее время подключения
                "current_uptime_s": 120.0,# текущая сессия
                "node_cache_size": 25,    # узлов в кэше
                "active_polls": 2,        # активных poll loop'ов
                "subscribed_tags": 10,    # подписанных тегов
                "is_connected": True,     # текущий статус
                "is_watchdog_active": True # watchdog запущен
            }
        """
        stats = self._stats.copy()

        if self._stats["connected_at"]:
            stats["current_uptime_s"] = round(
                (datetime.now(timezone.utc) - self._stats["connected_at"]).total_seconds(), 1
            )
        else:
            stats["current_uptime_s"] = 0.0

        stats["node_cache_size"]    = len(self._node_cache)
        stats["active_polls"]       = sum(1 for p in self._poll_loops.values() if p["active"])
        stats["subscribed_tags"]    = len(self.subscribed_tags)
        stats["is_connected"]       = self.is_connected
        stats["is_watchdog_active"] = self.is_watchdog_active

        return stats

    def reset_stats(self) -> None:
        """
        Сбросить счётчики статистики.

        Не сбрасывает connected_at и total_uptime_s — они привязаны к сессии.
        """
        for key in ("reads", "writes", "read_errors", "write_errors", "reconnects"):
            self._stats[key] = 0
        self._stats["last_read_ms"]  = 0.0
        self._stats["last_write_ms"] = 0.0
        logger.info("Stats counters reset")
