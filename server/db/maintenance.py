"""
maintenance — разовая чистка БД от «осадочных» тегов при старте сервера.

Таблицы tag_values и tags только пополняются (запись при первом приходе данных)
и не чистятся при смене пресета конфига на стенде. После переключения servers.json
теги прежнего пресета остаются в БД и утекают клиенту через /tags/latest.

prune_unconfigured_tags() удаляет такие осадочные строки, сверяясь с активным
конфигом через client_manager.is_configured_node(). Вызывается из main.lifespan
на старте — самоочистка при каждом деплое/рестарте.
"""
# logging — сообщить в лог, сколько строк удалено.
import logging
# SessionLocal — синхронная сессия SQLite (этот код не в event loop'е запроса).
from db.database import SessionLocal
# Модели таблиц, которые чистим/проверяем.
from db.models import TagValue, Tag, TagHistory
# Предикат «NodeId есть в активном servers.json» (с учётом массивных [N]).
from protocol_backend.protocol_client.client_manager import is_configured_node

log = logging.getLogger(__name__)


def prune_unconfigured_tags() -> tuple[int, int]:
    """Удалить из БД теги, которых нет в активном конфиге.

    tag_values — чистим полностью (нет внешних ключей на эту таблицу): именно её
    читает /tags/latest, поэтому это и убирает «призраков» у клиента.

    tags — удаляем только строки БЕЗ ссылок из tag_history, чтобы не осиротить
    историю прошлых испытаний (TagHistory.tag_id → tags.id). Осадочные теги с
    историей оставляем как есть — они безвредны (в /tags/latest не попадают).

    Возвращает (removed_values, removed_tags) для лога.
    """
    db = SessionLocal()
    try:
        # ── tag_values: последние значения, источник списка каналов клиента ──────
        removed_values = 0
        for row in db.query(TagValue).all():
            if not is_configured_node(row.tag_id):
                db.delete(row)
                removed_values += 1

        # ── tags: справочник; бережём строки, на которые ссылается tag_history ───
        used_tag_ids = {tid for (tid,) in db.query(TagHistory.tag_id).distinct()}
        removed_tags = 0
        for tag in db.query(Tag).all():
            if not is_configured_node(tag.node_id) and tag.id not in used_tag_ids:
                db.delete(tag)
                removed_tags += 1

        db.commit()
        if removed_values or removed_tags:
            log.info(
                "Прунинг осадочных тегов: tag_values -%d, tags -%d",
                removed_values, removed_tags,
            )
        return removed_values, removed_tags
    finally:
        db.close()
