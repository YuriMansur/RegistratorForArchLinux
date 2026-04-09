import json
from datetime import datetime
from typing import Optional, AsyncGenerator

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TagHistory, Tag


def _attach_tag_names(rows: list) -> list[TagHistory]:
    result = []
    for h, tag in rows:
        h.tag_name = tag.name if tag else ""
        result.append(h)
    return result


class HistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def count_range(self, from_dt: datetime, to_dt: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(TagHistory)
            .where(TagHistory.recorded_at >= from_dt.replace(tzinfo=None))
            .where(TagHistory.recorded_at <= to_dt.replace(tzinfo=None))
        )
        return (await self.db.execute(stmt)).scalar_one()

    async def get_by_checkout(self, checkout_id: int) -> list[TagHistory]:
        stmt = (
            select(TagHistory, Tag)
            .outerjoin(Tag, TagHistory.tag_id == Tag.id)
            .where(TagHistory.test_id == checkout_id)
            .order_by(TagHistory.recorded_at)
        )
        rows = (await self.db.execute(stmt)).all()
        return _attach_tag_names(rows)

    async def get_recent(self, limit: int) -> list[TagHistory]:
        stmt = (
            select(TagHistory, Tag)
            .outerjoin(Tag, TagHistory.tag_id == Tag.id)
            .order_by(TagHistory.recorded_at.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()
        return _attach_tag_names(rows)

    async def get_range(
        self,
        from_dt: datetime,
        to_dt: datetime,
        tags: Optional[list[str]] = None,
        max_points_per_tag: Optional[int] = None,
    ) -> list[TagHistory]:
        from_naive = from_dt.replace(tzinfo=None)
        to_naive   = to_dt.replace(tzinfo=None)

        if max_points_per_tag:
            return await self._get_range_sampled(from_naive, to_naive, tags, max_points_per_tag)

        stmt = (
            select(TagHistory, Tag)
            .outerjoin(Tag, TagHistory.tag_id == Tag.id)
            .where(TagHistory.recorded_at >= from_naive)
            .where(TagHistory.recorded_at <= to_naive)
        )
        if tags:
            stmt = stmt.where(Tag.name.in_(tags))
        stmt = stmt.order_by(TagHistory.recorded_at)
        rows = (await self.db.execute(stmt)).all()
        return _attach_tag_names(rows)

    async def _get_range_sampled(
        self,
        from_naive: datetime,
        to_naive: datetime,
        tags: Optional[list[str]],
        max_points_per_tag: int,
    ) -> list[TagHistory]:
        """
        Прореживание на уровне SQL через ROW_NUMBER() + COUNT() OVER PARTITION BY tag_id.
        SQLite поддерживает window functions начиная с версии 3.25 (2018).
        Каждый тег получает ровно max_points_per_tag точек, равномерно распределённых.
        """
        tag_filter = ""
        params: dict = {
            "from_dt":   from_naive,
            "to_dt":     to_naive,
            "max_pts":   max_points_per_tag,
        }

        if tags:
            placeholders = ", ".join(f":tag_{i}" for i in range(len(tags)))
            tag_filter = f"AND t.name IN ({placeholders})"
            for i, tag in enumerate(tags):
                params[f"tag_{i}"] = tag

        sql = text(f"""
            SELECT
                h.id, h.test_id, h.tag_id, h.value, h.recorded_at,
                t.name AS tag_name
            FROM (
                SELECT
                    h.*,
                    ROW_NUMBER() OVER (PARTITION BY h.tag_id ORDER BY h.recorded_at) AS rn,
                    COUNT(*)     OVER (PARTITION BY h.tag_id)                         AS total
                FROM tag_history h
                JOIN tags t ON h.tag_id = t.id
                WHERE h.recorded_at >= :from_dt
                  AND h.recorded_at <= :to_dt
                  {tag_filter}
            ) h
            JOIN tags t ON h.tag_id = t.id
            WHERE (h.rn - 1) % MAX(1, h.total / :max_pts) = 0
            ORDER BY h.recorded_at
        """)

        rows = (await self.db.execute(sql, params)).mappings().all()

        result = []
        for row in rows:
            h = TagHistory(
                id=row["id"],
                test_id=row["test_id"],
                tag_id=row["tag_id"],
                value=row["value"],
                recorded_at=row["recorded_at"],
            )
            h.tag_name = row["tag_name"] or ""
            result.append(h)
        return result


    async def stream_range(
        self,
        from_dt: datetime,
        to_dt: datetime,
        tags: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """Стриминг строк истории в формате NDJSON (одна строка = один JSON + \\n)."""
        from_naive = from_dt.replace(tzinfo=None)
        to_naive   = to_dt.replace(tzinfo=None)

        tag_filter = ""
        params: dict = {"from_dt": from_naive, "to_dt": to_naive}
        if tags:
            placeholders = ", ".join(f":tag_{i}" for i in range(len(tags)))
            tag_filter = f"AND t.name IN ({placeholders})"
            for i, tag in enumerate(tags):
                params[f"tag_{i}"] = tag

        sql = text(f"""
            SELECT h.id, h.test_id, h.tag_id, h.value, h.recorded_at, t.name AS tag_name
            FROM tag_history h
            JOIN tags t ON h.tag_id = t.id
            WHERE h.recorded_at >= :from_dt
              AND h.recorded_at <= :to_dt
              {tag_filter}
            ORDER BY h.recorded_at
        """)

        result = await self.db.execute(sql, params)
        for row in result.mappings():
            yield json.dumps({
                "tag_name":    row["tag_name"] or "",
                "value":       row["value"],
                "recorded_at": row["recorded_at"].isoformat()
                               if hasattr(row["recorded_at"], "isoformat")
                               else str(row["recorded_at"]),
            }) + "\n"


class HistoryService:
    def __init__(self, repo: HistoryRepository):
        self.repo = repo

    async def count_range(self, from_dt: datetime, to_dt: datetime) -> int:
        return await self.repo.count_range(from_dt, to_dt)

    async def get_by_checkout(self, checkout_id: int) -> list[TagHistory]:
        return await self.repo.get_by_checkout(checkout_id)

    async def get_recent(self, limit: int) -> list[TagHistory]:
        return await self.repo.get_recent(limit)

    async def get_range(
        self,
        from_dt: datetime,
        to_dt: datetime,
        tags: Optional[list[str]] = None,
        max_points: Optional[int] = None,
    ) -> list[TagHistory]:
        # max_points — суммарный лимит, делим на количество тегов
        max_per_tag = None
        if max_points and tags:
            max_per_tag = max(1, max_points // len(tags))
        elif max_points:
            max_per_tag = max_points
        return await self.repo.get_range(from_dt, to_dt, tags, max_per_tag)
