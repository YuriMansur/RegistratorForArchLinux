"""
Утилита для thread-safe записи OPC UA тегов в SQLite.
Вызывается из ServerManager._on_data_received().
"""
from datetime import datetime, timezone
from db.database import SessionLocal
from db.models import TagValue, Tag, TagHistory


def write_tag(
    tag_id          : str,
    value,
    tag_name        : str = "",
    record_history  : bool = True,
    test_id         : int | None = None,
    recorded_at     : datetime | None = None,
) -> None:
    """Записать текущее значение тега.
    - Если value — список/кортеж, каждый элемент пишется как отдельный тег tag_id[i].
    - Всегда обновляет TagValue.
    - Если тег есть в справочнике Tag — обновляет Tag.value/updated_at.
    - record_history=True — пишет строку в TagHistory (с test_id если задан).
    - recorded_at — явный timestamp для TagHistory (None = datetime.now()).
    """
    # Массив → разворачиваем в отдельные теги
    if isinstance(value, (list, tuple)):
        now = recorded_at if recorded_at is not None else datetime.now(timezone.utc)
        for i, item in enumerate(value):
            write_tag(
                tag_id          = f"{tag_id}[{i}]",
                value           = item,
                tag_name        = f"{tag_name}[{i}]" if tag_name else f"{tag_id}[{i}]",
                record_history  = record_history,
                test_id=test_id,
                recorded_at=now,
            )
        return

    serialized = _serialize(value)
    now = recorded_at if recorded_at is not None else datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        # ── TagValue (неизменная логика) ──────────────────────────────────────
        row = db.get(TagValue, tag_id)
        if row is None:
            row = TagValue(tag_id=tag_id, tag_name=tag_name or tag_id)
            db.add(row)
        row.value = serialized
        row.updated_at = now
        if tag_name:
            row.tag_name = tag_name

        # ── Tag справочник — upsert: обновляем если есть, создаём если нет ────
        tag_row = db.query(Tag).filter(Tag.node_id == tag_id).first()
        if tag_row is None:
            tag_row = Tag(node_id=tag_id, name=tag_name or tag_id, units="")
            db.add(tag_row)
            db.flush()  # получаем tag_row.id до commit
        tag_row.value = serialized
        tag_row.updated_at = now
        if tag_name and tag_row.name == tag_id:
            tag_row.name = tag_name  # уточняем имя если раньше не было
        tag_fk: int = tag_row.id

        # TagHistory
        if record_history:
            db.add(TagHistory(
                test_id     = test_id,
                tag_id      = tag_fk,
                value       = serialized,
                recorded_at = now,
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
