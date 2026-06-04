# re — встроенный модуль регулярных выражений, используется для разбора NodeId строк.
import re
# json — для загрузки конфига серверов из servers.json.
import json
# logging — стандартный логгер Python для вывода info/warning/error.
import logging
# threading — для таймеров переподключения и фоновых потоков экспорта.
import threading
# Path — для построения абсолютного пути к servers.json относительно файла.
from pathlib import Path
# datetime — для фиксации времени начала и конца сессии испытания.
from datetime import datetime, timezone, timedelta
# OpcUaBackend — менеджер OPC UA соединений, через него всё общение с ПЛК.
from protocol_backend.protocol_client.opcua.opcua_backend.opcua_backend import OpcUaBackend
# tag_writer — пишет текущее значение тега и опционально историю в SQLite.
from db import tag_writer
# session_exporter — экспортирует данные сессии испытания в xlsx/docx.
from db import session_exporter
# test_manager — создаёт и завершает записи об испытании в таблице checkouts.
from db import test_manager
# live_data — хранилище последних значений тегов в памяти для /tags/live.
from services import live_data


# Путь к JSON-конфигу серверов: server/config/servers.json.
# Этот файл лежит в server/protocol_backend/protocol_client/ — поднимаемся на 3 уровня до server/.
_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "servers.json"

# Логгер для этого модуля — имя совпадает с именем файла.
log = logging.getLogger(__name__)


def _load_config(path: Path) -> list[dict]:
    """Загрузить и провалидировать конфиг серверов из JSON.
    Каждый тег разворачивается из короткого идентификатора в полный NodeId формата
    "ns=N;s=Identifier". Имена тегов в subscribe/polls/control заменяются на NodeId.
    Args:
        path (Path): Путь к servers.json.
    Returns:
        Список dict'ов с готовой к использованию конфигурацией каждого сервера."""
    # Читаем файл как UTF-8, чтобы корректно обрабатывать любые имена.
    raw = json.loads(path.read_text(encoding="utf-8"))
    servers = []
    # Перебираем все серверы из верхнеуровневого ключа "servers".
    for srv in raw.get("servers", []):
        name = srv["name"]
        # Пространство имён OPC UA — общее для всех тегов этого сервера.
        ns = srv.get("ns", 2)
        # Маппинг короткое имя → NodeId. Пример: "rDTAT" → "ns=2;s=Application....rDTAT".
        tag_map: dict[str, str] = {
            tag_name: f"ns={ns};s={ident}"
            for tag_name, ident in srv.get("tags", {}).items()
        }

        # Проверяем что все имена в subscribe/polls/control действительно есть в tags.
        def resolve(tag_name: str) -> str:
            if tag_name not in tag_map:
                raise ValueError(
                    f"Сервер {name}: тег '{tag_name}' не найден в секции 'tags'"
                )
            return tag_map[tag_name]

        # Подписки — переводим имена в NodeId.
        subscribe = [resolve(t) for t in srv.get("subscribe", [])]
        # Polls — каждая группа тоже разворачивается в NodeId.
        polls = []
        for poll in srv.get("polls", []):
            polls.append({
                "name":       poll["name"],
                "interval":   poll["interval"],
                "sequential": poll.get("sequential", False),
                "nodes":      [resolve(t) for t in poll.get("tags", [])],
            })
        # Control-теги: ключи "in_process"/"end" → NodeId.
        control = {key: resolve(tag_name) for key, tag_name in srv.get("control", {}).items()}

        servers.append({
            "name":               name,
            "endpoint":           srv["endpoint"],
            "auto_reconnect":     srv.get("auto_reconnect", True),
            "reconnect_interval": srv.get("reconnect_interval", 5),
            "tag_map":            tag_map,
            "subscribe":          subscribe,
            "polls":              polls,
            "control":            control,
        })
    return servers


# Конфиги всех серверов — загружаются при импорте модуля.
_SERVERS = _load_config(_CONFIG_PATH)

# Обратный маппинг NodeId → имя тега, агрегированный по всем серверам.
# Нужен чтобы при записи в БД получить человекочитаемое имя по NodeId.
_NODE_NAMES: dict[str, str] = {
    node_id: tag_name
    for srv in _SERVERS
    for tag_name, node_id in srv["tag_map"].items()
}

# Множество всех NodeId, помеченных как control в любом из серверов —
# они не пишутся в историю, только меняют состояние сессии испытания.
_CONTROL_TAGS: set[str] = {
    node_id
    for srv in _SERVERS
    for node_id in srv["control"].values()
}

# «Белый список» NodeId активного конфига — все теги, объявленные в секциях "tags".
# По нему отсеиваются «осадочные» теги от прежних пресетов (см. is_configured_node).
_CONFIGURED_NODES: frozenset[str] = frozenset(_NODE_NAMES)

# Суффикс массивного элемента вида "...rDavDDB_kPa[3]" — для проверки по базовому NodeId.
_ARRAY_SUFFIX_RE = re.compile(r"\[\d+\]$")


def is_configured_node(node_id: str) -> bool:
    """True, если NodeId принадлежит активному конфигу (servers.json).

    Массивные элементы хранятся в БД как "{node_id}[i]" — проверяем по базовому
    NodeId, отрезав суффикс [N]. Используется фильтром /tags/latest и прунингом БД
    при старте, чтобы теги от ранее задеплоенных пресетов не утекали клиенту."""
    base = _ARRAY_SUFFIX_RE.sub("", node_id)
    return base in _CONFIGURED_NODES


class ServerManager:
    """Управляет OPC UA серверами. Пишет данные тегов в SQLite через tag_writer."""

    def __init__(self):
        # OpcUaBackend — низкоуровневый менеджер соединений и потоков.
        self._backend = OpcUaBackend()
        # Таймеры переподключения: server_name → threading.Timer.
        # Хранятся чтобы отменить предыдущий таймер при успешном подключении.
        self._timers: dict[str, threading.Timer] = {}
        # Конфиги серверов: name → dict из _SERVERS.
        # Нужен для быстрого доступа к настройкам по имени сервера.
        self._config: dict[str, dict] = {}
        # Флаг — идёт ли сейчас сессия испытания.
        # True: данные пишутся в историю. False: только текущее значение.
        self._recording: bool = False
        # Время начала текущей сессии — фиксируется при inProcess=True.
        # Используется при экспорте для определения диапазона данных.
        self._session_start: datetime | None = None
        # ID текущего испытания в таблице checkouts.
        # Привязывает TagHistory записи к конкретному испытанию.
        self._current_test_id: int | None = None
        # Время последнего обновления данных от ПЛК — используется watchdog'ом второго уровня.
        self._last_data_at: datetime | None = None
        # Таймер watchdog'а второго уровня — проверяет что данные обновляются регулярно.
        self._data_watchdog_timer: threading.Timer | None = None
        # Последняя целая секунда, записанная в tag_history — для дедупа "одна точка в секунду".
        # Сбрасывается при старте/окончании каждой сессии испытания.
        self._last_history_second: datetime | None = None
        # Регистрируем серверы в backend и подключаем callback'и.
        self._setup()

    # ── Публичный API ─────────────────────────────────────────────────────────

    def start(self):
        """Подключиться ко всем серверам из конфига.
        Вызывается при старте приложения из main.py (lifespan)."""
        # При перезапуске сервера могут остаться незакрытые испытания (ended_at=NULL).
        # Это случается если сервер упал или был перезапущен в середине теста.
        # Закрываем их сразу, чтобы клиент не показывал "в процессе" бесконечно.
        self._close_orphan_checkouts()
        # Проходим по всем зарегистрированным серверам и запускаем подключение.
        # connect_server создаёт worker thread и инициирует OPC UA соединение.
        for name in self._config:
            self._backend.connect_server(name)
        # Запускаем watchdog второго уровня — следит что данные обновляются регулярно.
        self._schedule_data_watchdog()

    def _close_orphan_checkouts(self):
        """Закрыть все незавершённые испытания оставшиеся от предыдущего запуска.
        Вызывается при старте до подключения к ПЛК."""
        from db.database import SessionLocal
        from db.models import Checkout
        db = SessionLocal()
        try:
            orphans = db.query(Checkout).filter(Checkout.ended_at.is_(None)).all()
            if not orphans:
                return
            now = datetime.now(timezone.utc)
            for checkout in orphans:
                checkout.ended_at = now
                log.warning(
                    "Закрываю осиротевшее испытание id=%s started_at=%s (сервер был перезапущен)",
                    checkout.id, checkout.started_at,
                )
            db.commit()
        finally:
            db.close()

    def stop(self):
        """Корректно остановить всё: отменить таймеры и отключить серверы.
        Вызывается при завершении приложения из main.py (lifespan)."""
        # Заглушаем логи asyncua — при остановке он генерирует много шума.
        logging.getLogger("asyncua").setLevel(logging.CRITICAL)
        # Отменяем watchdog второго уровня.
        if self._data_watchdog_timer:
            self._data_watchdog_timer.cancel()
        # Отменяем все активные таймеры переподключения — иначе они попытаются
        # переподключиться уже после того как backend остановлен.
        for timer in self._timers.values():
            timer.cancel()
        # Отключаем все серверы и ждём завершения потоков (blocking внутри stop_all).
        self._backend.stop_all()

    def _schedule_data_watchdog(self):
        """Запланировать следующую проверку watchdog'а через 60 секунд."""
        self._data_watchdog_timer = threading.Timer(60.0, self._data_watchdog_check)
        self._data_watchdog_timer.daemon = True
        self._data_watchdog_timer.start()

    def _data_watchdog_check(self):
        """Watchdog второго уровня: если данные не обновлялись 2+ минуты — реконнект.
        Срабатывает когда asyncua завис после реконнекта (известный баг библиотеки)."""
        now = datetime.now(timezone.utc)
        # Если данные были хотя бы раз и последнее обновление > 2 минут назад — реконнект.
        if self._last_data_at is not None:
            age = now - self._last_data_at
            if age > timedelta(minutes=2):
                log.warning(
                    "Data watchdog: no data for %.0f seconds — forcing reconnect",
                    age.total_seconds()
                )
                # Принудительный реконнект всех серверов.
                for name in self._config:
                    self._backend.disconnect_server(name)
                    self._schedule_reconnect(name, 3)
        # Планируем следующую проверку.
        self._schedule_data_watchdog()

    def write_tag(self, srv: str, node_id: str, value):
        """Записать значение в тег на ПЛК.
        Args:
            srv (str): Имя сервера (например "PLC1").
            node_id (str): Адрес тега (например "ns=2;s=...").
            value: Значение для записи."""
        # Делегируем запись в backend — он передаёт команду в worker thread.
        self._backend.write_node(srv, node_id, value)

    # ── Инициализация ─────────────────────────────────────────────────────────

    def _setup(self):
        """Зарегистрировать все серверы из _SERVERS в backend и подключить callback'и.
        Вызывается один раз в __init__."""
        for cfg in _SERVERS:
            name = cfg["name"]
            # Сохраняем конфиг по имени для быстрого доступа в обработчиках.
            self._config[name] = cfg
            # Регистрируем сервер в backend (без подключения — только конфиг).
            # Подключение произойдёт при вызове start().
            self._backend.add_server(name, cfg["endpoint"])
        # Подключаем наши методы как callback'и backend'а.
        self._wire_callbacks()

    def _wire_callbacks(self):
        """Назначить обработчики событий backend'а.
        Вызывается один раз из _setup() после регистрации всех серверов."""
        b = self._backend
        # При подключении к серверу — запустить подписки, polls и watchdog.
        b.on_connected        = self._on_connected
        # При отключении — запустить таймер переподключения (если auto_reconnect).
        b.on_disconnected     = self._on_disconnected
        # При получении данных от подписки (control теги) — записать в SQLite.
        b.on_data_updated     = self._on_data_received
        # При завершении poll-цикла — записать все теги батча с одним timestamp.
        b.on_poll_batch       = self._on_poll_batch
        # При ошибке соединения — просто логируем, без дополнительной логики.
        b.on_connection_error = lambda srv, err: log.error("OPC error [%s]: %s", srv, err)

    # ── Обработчики событий backend ───────────────────────────────────────────

    def _on_connected(self, srv: str):
        """Вызывается когда OPC UA соединение с сервером установлено.
        Запускает подписки на теги, циклические опросы и watchdog.
        Args:
            srv (str): Имя сервера."""
        # Отменяем таймер переподключения — мы уже подключились, он больше не нужен.
        self._cancel_timer(srv)
        log.info("Connected to %s", srv)
        # Берём конфиг этого сервера чтобы знать какие теги подписывать и опрашивать.
        cfg = self._config.get(srv, {})
        subscribe_tags = cfg.get("subscribe", [])
        # Подписываемся на каждый тег из списка subscribe.
        # Подписка — самый быстрый способ получать данные: сервер сам присылает обновления.
        for node_id in subscribe_tags:
            self._backend.subscribe_tag(srv, node_id)
        if subscribe_tags:
            # Сразу читаем текущие значения подписанных тегов —
            # без этого первое значение придёт только при следующем изменении на ПЛК.
            self._backend.read_multiple_nodes(srv, subscribe_tags)
        # Запускаем все группы циклического опроса из конфига.
        # Poll читает теги с заданным интервалом независимо от изменений.
        for poll in cfg.get("polls", []):
            self._backend.start_polling(
                srv, poll["name"], poll["nodes"],
                poll["interval"], poll.get("sequential", False)
            )
        # Запускаем watchdog — он будет проверять связь каждые 10 секунд.
        # При потере связи вызовет on_disconnected → запустит переподключение.
        self._backend.start_watchdog(srv, interval=10.0)

    def _on_disconnected(self, srv: str):
        """Вызывается когда соединение с сервером потеряно (штатно или по watchdog).
        Если в конфиге auto_reconnect=True — планирует повторное подключение.
        Args:
            srv (str): Имя сервера."""
        log.warning("Disconnected from %s", srv)
        cfg = self._config.get(srv, {})
        # Проверяем настройку автоматического переподключения в конфиге сервера.
        if cfg.get("auto_reconnect", True):
            interval = cfg.get("reconnect_interval", 5)
            # Планируем переподключение через заданный интервал.
            self._schedule_reconnect(srv, interval)

    def _schedule_reconnect(self, name: str, interval: float):
        """Запланировать переподключение к серверу через threading.Timer.
        Args:
            name (str): Имя сервера.
            interval (float): Через сколько секунд попробовать переподключиться."""
        # Отменяем предыдущий таймер если он уже был — не дублируем попытки.
        self._cancel_timer(name)
        # Создаём одноразовый таймер — через interval секунд вызовет connect_server.
        # daemon=True — таймер не помешает завершению программы.
        t = threading.Timer(interval, self._backend.connect_server, args=[name])
        t.daemon = True
        t.start()
        # Сохраняем таймер чтобы можно было отменить при успешном подключении.
        self._timers[name] = t
        log.info("Reconnecting to %s in %ss...", name, interval)

    def _cancel_timer(self, name: str):
        """Отменить активный таймер переподключения для сервера.
        Args:
            name (str): Имя сервера."""
        # pop удаляет таймер из словаря и возвращает его (или None если не было).
        t = self._timers.pop(name, None)
        if t:
            # Отменяем таймер — если он ещё не сработал, он не будет вызван.
            t.cancel()

    # ── Маршрутизация входящих данных ─────────────────────────────────────────

    def _on_data_received(self, srv: str, nid: str, val):
        """Обработчик данных от подписки (control теги: inProcess, End).
        Poll-теги обрабатываются в _on_poll_batch с единым timestamp.
        Args:
            srv (str): Имя сервера-источника.
            nid (str): NodeId тега.
            val: Новое значение тега."""
        nid = self._normalize_nid(nid)
        tag_name = _NODE_NAMES.get(nid, nid)

        # Управляющие теги — особая обработка: не пишем в историю.
        if nid in _CONTROL_TAGS:
            tag_writer.write_tag(tag_id=nid, value=val, tag_name=tag_name, record_history=False)
            self._handle_control(srv, nid, val)
            return

        # Не-control теги от on_data_updated (не из poll) — пишем текущее значение без истории.
        # История пишется в _on_poll_batch с единым timestamp.
        tag_writer.write_tag(tag_id=nid, value=val, tag_name=tag_name, record_history=False)

    def _on_poll_batch(self, srv: str, poll_name: str, batch: dict):
        """Обработчик завершения poll-цикла — все теги группы с единым timestamp.
        Args:
            srv (str): Имя сервера.
            poll_name (str): Имя группы опроса.
            batch (dict): {node_id: value} — все теги, прочитанные за один цикл."""
        now = datetime.now(timezone.utc)
        # Округляем до целой секунды — гарантия "одна точка в секунду" в tag_history.
        # При period polls ~0.8с в одну секунду может попасть 1-2 батча; дедуп оставит первый.
        second = now.replace(microsecond=0)

        # ── Шаг 1: control-теги обрабатываем ПЕРВЫМИ ────────────────────────────
        # Иначе если inProcess стоит последним в списке polls.tags, при старте сессии
        # сенсоры этого батча получают record_history=False (старое значение _recording).
        normalized_batch = {self._normalize_nid(nid): val for nid, val in batch.items()}
        for nid, val in normalized_batch.items():
            if nid in _CONTROL_TAGS:
                self._handle_control(srv, nid, val)

        # ── Шаг 2: дедуп. Пишем history только если в этой секунде ещё не писали ──
        # Если же мы пишем — фиксируем _last_history_second чтобы следующий батч в той
        # же секунде пропустить. live_data и tag_values обновляются всегда.
        write_history = self._recording and (second != self._last_history_second)
        if write_history:
            self._last_history_second = second

        # ── Шаг 3: пишем сенсоры ────────────────────────────────────────────────
        live_batch: dict[str, tuple[str, datetime]] = {}
        for nid, val in normalized_batch.items():
            if nid in _CONTROL_TAGS:
                continue  # уже обработаны в шаге 1
            tag_name = _NODE_NAMES.get(nid, nid)
            tag_writer.write_tag(
                tag_id=nid, value=val, tag_name=tag_name,
                record_history=write_history,
                test_id=self._current_test_id,
                # В историю — округлённая секунда (для красивых "ровно :01, :02..." на графиках).
                # В tag_values попадёт то же, но это OK — поле "Обновлено" просто без миллисекунд.
                recorded_at=second,
            )
            from db.tag_writer import _serialize
            if isinstance(val, (list, tuple)):
                for i, item in enumerate(val):
                    live_batch[f"{tag_name}[{i}]"] = (_serialize(item), now)
            else:
                live_batch[tag_name] = (_serialize(val), now)
        live_data.update_batch(live_batch)
        if live_batch:
            log.debug("[%s] %s", srv, {k: v[0] for k, v in live_batch.items()})
        # Обновляем время последнего успешного получения данных для watchdog'а.
        self._last_data_at = now

    def _handle_control(self, srv: str, nid: str, val):
        """Обработать управляющий тег — запустить или завершить сессию испытания.
        Args:
            srv (str): Имя сервера-источника (для выбора маппинга control-тегов).
            nid (str): NodeId тега.
            val: Значение тега (ожидаем булево)."""
        # Берём NodeId in_process/end именно того сервера, с которого пришёл тег —
        # допускаем что у разных серверов могут быть разные адреса control-тегов.
        control = self._config.get(srv, {}).get("control", {})
        in_process_nid = control.get("in_process")
        end_nid = control.get("end")

        # inProcess=True и сессия ещё не запущена → СТАРТ испытания.
        if nid == in_process_nid and bool(val) and not self._recording:
            # Включаем запись истории для всех последующих тегов.
            self._recording = True
            # Фиксируем время начала — понадобится при экспорте.
            self._session_start = datetime.now(timezone.utc)
            # Создаём запись в таблице checkouts и получаем её ID.
            self._current_test_id = test_manager.start_test()
            # Сброс дедуп-трекера: первая секунда нового испытания должна записаться.
            self._last_history_second = None
            log.info("Session started (test_id=%s)", self._current_test_id)

        # inProcess=False пока сессия активна → неявный конец испытания.
        # Это случается когда ПЛК сбросил inProcess раньше чем послал End=True,
        # или подписка пропустила пульс End=True (он короче publishing interval 500мс).
        elif nid == in_process_nid and not bool(val) and self._recording:
            self._recording = False
            # Сброс дедуп-трекера — следующая сессия начнётся "с чистого листа".
            self._last_history_second = None
            session_end = datetime.now(timezone.utc)
            test_manager.end_test(self._current_test_id)
            log.warning(
                "Session ended implicitly via inProcess=False (test_id=%s), exporting...",
                self._current_test_id,
            )
            threading.Thread(
                target=session_exporter.export_session,
                args=(self._session_start, session_end, self._current_test_id),
                daemon=True,
            ).start()
            self._session_start = None
            self._current_test_id = None

        # End=True и сессия была запущена → КОНЕЦ испытания.
        elif nid == end_nid and bool(val) and self._recording:
            # Выключаем запись истории.
            self._recording = False
            # Сброс дедуп-трекера — следующая сессия начнётся "с чистого листа".
            self._last_history_second = None
            # Фиксируем время конца сессии.
            session_end = datetime.now(timezone.utc)
            # Закрываем запись в checkouts (проставляем ended_at).
            test_manager.end_test(self._current_test_id)
            log.info("Session ended (test_id=%s), exporting...", self._current_test_id)
            # Запускаем экспорт в отдельном потоке — он генерирует xlsx/docx,
            # что может занять несколько секунд. daemon=True — не блокирует завершение.
            threading.Thread(
                target=session_exporter.export_session,
                args=(self._session_start, session_end, self._current_test_id),
                daemon=True,
            ).start()
            # Сбрасываем состояние — готовы к следующему испытанию.
            self._session_start = None
            self._current_test_id = None

    # ── Вспомогательные методы ────────────────────────────────────────────────

    @staticmethod
    def _normalize_nid(nid: str) -> str:
        """Привести NodeId к строковому формату "ns=X;s=...".
        asyncua иногда передаёт NodeId как объект со строковым представлением
        вида "NodeId(NamespaceIndex=2, Identifier='...')" — разбираем его регуляркой.
        Args:
            nid (str): NodeId в любом формате."""
        # Если строка уже в нужном формате — возвращаем как есть без разбора.
        if not nid.startswith("NodeId("):
            return nid
        # Ищем номер namespace: NamespaceIndex=2 → группа "2".
        m_ns = re.search(r"NamespaceIndex=(\d+)", nid)
        # Ищем идентификатор узла: Identifier='Application.GVL.ForUra' → группа "Application.GVL.ForUra".
        m_id = re.search(r"Identifier='([^']+)'", nid)
        # Если обе части успешно найдены — собираем строку в стандартном формате.
        if m_ns and m_id:
            return f"ns={m_ns.group(1)};s={m_id.group(1)}"
        # Если разбор не удался — возвращаем исходную строку как есть.
        return nid
