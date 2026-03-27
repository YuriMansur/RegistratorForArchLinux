"""
Утилита для thread-safe записи OPC UA тегов в SQLite.
Вызывается из ServerManager._on_data_received().
"""
from datetime import datetime
from database import SessionLocal
from models import TagValue, TagHistory


def write_tag(tag_id: str, value, tag_name: str = "") -> None:
    """Записать (или обновить) последнее значение тега и добавить запись в историю."""
    serialized = _serialize(value)
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        # Обновляем последнее значение
        row = db.get(TagValue, tag_id)
        if row is None:
            row = TagValue(tag_id=tag_id, tag_name=tag_name or tag_id)
            db.add(row)
        row.value = serialized
        row.updated_at = now
        if tag_name:
            row.tag_name = tag_name

        # Пишем в историю
        db.add(TagHistory(
            tag_id=tag_id,
            tag_name=tag_name or tag_id,
            value=serialized,
            recorded_at=now,
        ))
        db.commit()
    finally:
        db.close()


def _serialize(value) -> str:
    """Привести значение тега к строке для хранения в БД."""
    if isinstance(value, (list, tuple)):
        return str([round(float(v), 4) if isinstance(v, float) else v for v in value])
    if isinstance(value, float):
        return str(round(value, 6))
    return str(value)
