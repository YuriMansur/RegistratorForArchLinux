"""
live_data — хранилище последних значений тегов в оперативной памяти.

Назначение:
    Позволяет отдавать GET /tags/live без обращения к SQLite — ответ за ~0мс.
    SQLite-запрос к TagValue занял бы ~5мс, что критично при опросе каждые 500мс.

Обновляется из client_manager._on_poll_batch() с единым timestamp для всей группы.
Читается из GET /tags/live эндпоинта (api.py).

Потокобезопасность:
    Данные обновляются из OPC UA потока, читаются из asyncio (FastAPI).
    threading.Lock защищает от race condition при одновременном чтении и записи.
"""
# threading — для потокобезопасного доступа к данным из разных потоков.
import threading
# datetime — тип timestamp в батче обновления.
from datetime import datetime

# Мьютекс для защиты _data от одновременного чтения и записи.
_lock = threading.Lock()

# Основное хранилище: tag_name → dict с полями tag_name, value, updated_at.
# Ключ — имя тега (например "values[0]"), а не NodeId, для удобства отображения.
_data: dict[str, dict] = {}


def update_batch(batch: dict[str, tuple[str, datetime]]) -> None:
    """Обновить несколько тегов за раз с единым timestamp.

    Вызывается из client_manager._on_poll_batch() после каждого цикла опроса.
    batch = {tag_name: (value_str, timestamp)} — все теги одного poll-цикла.

    Единый timestamp важен: все теги в батче прочитаны в один момент времени,
    клиент видит согласованный снимок, а не данные из разных моментов.
    """
    # Захватываем мьютекс — FastAPI может читать _data прямо сейчас.
    with _lock:
        for tag_name, (value, ts) in batch.items():
            # Обновляем или создаём запись для каждого тега в батче.
            _data[tag_name] = {
                "tag_name":   tag_name,          # имя тега для отображения
                "value":      value,             # строковое значение
                "updated_at": ts.isoformat(),    # ISO-строка для JSON-сериализации
            }


def get_all() -> list[dict]:
    """Вернуть список всех тегов с последними значениями.

    Вызывается из GET /tags/live эндпоинта.
    Возвращает копию данных чтобы не держать мьютекс пока FastAPI сериализует JSON.
    """
    # Захватываем мьютекс только на время копирования — не на время сериализации.
    with _lock:
        return list(_data.values())
