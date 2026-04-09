from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TagValue


class TagRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[TagValue]:
        result = await self.db.execute(select(TagValue).order_by(TagValue.tag_name))
        return result.scalars().all()


class TagService:
    def __init__(self, repo: TagRepository):
        self.repo = repo

    async def get_all(self) -> list[TagValue]:
        return await self.repo.get_all()
