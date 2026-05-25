"""
signals — маппинг технического имени тега в человекочитаемую подпись и единицу измерения.

Источник правды: server/config/signals.json (загружается при импорте, кэшируется в памяти).
Используется в session_exporter (xlsx/docx/png), tag_writer (запись в Tag.name/units),
и отдаётся клиенту через GET /signals.

Массивные теги (rDavDDB_kPa[0], [1], …) сопоставляются по базовому имени:
    get_label("rDavDDB_kPa[3]")  → "Давление DDB[3]"
    get_unit ("rDavDDB_kPa[3]")  → "кПа"
"""
# json — чтение JSON-конфига.
import json
# logging — для предупреждения если файл не найден или повреждён.
import logging
# re — отделение индекса массива "[N]" в конце имени.
import re
# Path — абсолютный путь к signals.json относительно расположения этого файла.
from pathlib import Path

log = logging.getLogger(__name__)

# Путь: server/services/signals.py → server/config/signals.json.
_PATH = Path(__file__).parent.parent / "config" / "signals.json"

# Регулярка для "[N]" в конце имени тега — массивные элементы вида rDavDDB_kPa[3].
_ARRAY_SUFFIX_RE = re.compile(r"\[\d+\]$")

# Кэш загруженного маппинга. Заполняется reload() при импорте модуля.
_signals: dict[str, dict] = {}


def reload() -> None:
    """Перечитать signals.json. Безопасно вызывать в любой момент времени.
    Если файл отсутствует или повреждён — оставляем пустой маппинг (фоллбек на технические имена)."""
    global _signals
    if not _PATH.exists():
        log.warning("signals.json не найден: %s — подписи и единицы будут пустыми", _PATH)
        _signals = {}
        return
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
        # Принимаем как обёрнутый формат {"signals": {...}}, так и плоский dict.
        _signals = raw.get("signals", raw) if isinstance(raw, dict) else {}
    except json.JSONDecodeError as e:
        log.error("signals.json повреждён: %s — фоллбек на пустой маппинг", e)
        _signals = {}


# Загружаем сразу при импорте — модуль готов к использованию без явного reload().
reload()


def _split(name: str) -> tuple[str, str]:
    """Разделить имя на (базовая часть, суффикс массива).
    Пример: "rDavDDB_kPa[3]" → ("rDavDDB_kPa", "[3]"). Если суффикса нет — второй элемент пустой."""
    m = _ARRAY_SUFFIX_RE.search(name)
    if not m:
        return name, ""
    return name[: m.start()], m.group(0)


def get_label(name: str) -> str:
    """Вернуть подпись для тега. Если тег неизвестен — возвращает исходное имя как фоллбек.
    Для массивов "[N]" приклеивается к подписи: 'Давление DDB' + '[3]' → 'Давление DDB[3]'."""
    base, suffix = _split(name)
    info = _signals.get(base)
    if not info:
        # Тег не описан в конфиге — возвращаем как есть (UI всё равно что-то покажет).
        return name
    return f"{info.get('label', base)}{suffix}"


def get_unit(name: str) -> str:
    """Вернуть единицу измерения для тега. Пустая строка если тег неизвестен или без единицы."""
    base, _ = _split(name)
    info = _signals.get(base)
    return info.get("unit", "") if info else ""


def get_all() -> dict[str, dict]:
    """Вернуть весь маппинг {имя: {label, unit}}. Используется эндпоинтом GET /signals."""
    return _signals
