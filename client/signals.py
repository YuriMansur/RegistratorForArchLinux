"""
signals — клиентский кэш маппинга {имя тега: {label, unit}}.

Источник: GET /signals на сервере (server/config/signals.json).
Кэш заполняется при первом обращении (или явном refresh()) и живёт до перезапуска клиента.
Если сервер недоступен — фоллбек на технические имена без единиц измерения,
UI продолжает работать как раньше.

Использование в виджетах:
    from signals import get_label, get_unit
    label = get_label("rDavDDB_kPa[3]")   # → "Давление DDB[3]"
    unit  = get_unit ("rDavDDB_kPa[3]")   # → "кПа"
"""
# logging — для предупреждения при недоступности сервера (без падения UI).
import logging
# re — выделение индекса массива "[N]" в конце имени.
import re

# api_client — HTTP-клиент к серверу, отсюда тащим /signals.
import api_client

log = logging.getLogger(__name__)

# "[N]" в конце имени — индекс массива вида rDavDDB_kPa[3].
_ARRAY_SUFFIX_RE = re.compile(r"\[\d+\]$")

# Кэш {имя: {label, unit}} — заполняется в refresh().
_cache: dict[str, dict] = {}
# Признак "загрузка хотя бы раз выполнялась" — без него каждое обращение делало бы HTTP.
_loaded: bool = False


def refresh() -> bool:
    """Принудительно перезагрузить подписи с сервера.
    Вызывать при старте приложения и при изменении signals.json на сервере.
    Возвращает True если загрузка успешна."""
    global _cache, _loaded
    try:
        # api_client.get_signals() сам ставит таймаут 2с — UI не зависает.
        _cache = api_client.get_signals() or {}
        _loaded = True
        return True
    except Exception as e:
        log.warning("Не удалось получить /signals: %s — подписи будут техническими", e)
        # Помечаем как загруженные, чтобы каждый последующий get_label/get_unit
        # не пытался снова сделать HTTP при каждом обращении.
        _loaded = True
        return False


def _ensure_loaded() -> None:
    """Ленивая инициализация — если refresh() ещё не звался, дёргаем его."""
    if not _loaded:
        refresh()


def _split(name: str) -> tuple[str, str]:
    """Разделить "rDavDDB_kPa[3]" на ("rDavDDB_kPa", "[3]"). Без суффикса — второй пустой."""
    m = _ARRAY_SUFFIX_RE.search(name)
    if not m:
        return name, ""
    return name[: m.start()], m.group(0)


def get_label(name: str) -> str:
    """Человекочитаемая подпись для тега. Если тег не описан — возвращает исходное имя."""
    _ensure_loaded()
    base, suffix = _split(name)
    info = _cache.get(base)
    if not info:
        return name
    return f"{info.get('label', base)}{suffix}"


def get_unit(name: str) -> str:
    """Единица измерения для тега. Пустая строка если тег без единицы или не описан."""
    _ensure_loaded()
    base, _ = _split(name)
    info = _cache.get(base)
    return info.get("unit", "") if info else ""


def get_display(name: str) -> str:
    """Полная подпись: 'Давление DDB[3] [кПа]' — label + индекс + единица в квадратных скобках.
    Если единицы нет, скобки не добавляются. Удобно для заголовков таблиц и легенды графиков."""
    label = get_label(name)
    unit = get_unit(name)
    return f"{label} [{unit}]" if unit else label
