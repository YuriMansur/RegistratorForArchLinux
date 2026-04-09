"""
Хранилище последних значений тегов в памяти.
Обновляется из ServerManager._on_poll_batch с единым timestamp.
Отдаётся через GET /tags/live без обращения к БД.
"""
import threading
from datetime import datetime

_lock = threading.Lock()
_data: dict[str, dict] = {}  # tag_name -> {value, updated_at}


def update_batch(batch: dict[str, tuple[str, datetime]]) -> None:
    """Обновить данные из батча. batch = {tag_name: (value, timestamp)}"""
    with _lock:
        for tag_name, (value, ts) in batch.items():
            _data[tag_name] = {
                "tag_name": tag_name,
                "value": value,
                "updated_at": ts.isoformat(),
            }


def get_all() -> list[dict]:
    with _lock:
        return list(_data.values())
