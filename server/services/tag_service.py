# select — для построения SQL SELECT запросов через SQLAlchemy ORM.
from sqlalchemy import select
# AsyncSession — асинхронная сессия для работы с БД в FastAPI эндпоинтах.
from sqlalchemy.ext.asyncio import AsyncSession

# ORM-модель таблицы tag_values — последние значения тегов.
from db.models import TagValue


class TagRepository:
    """Слой доступа к данным — запросы к таблице tag_values.

    tag_values хранит по одной строке на тег с последним значением.
    Используется эндпоинтом GET /tags/latest.
    """

    def __init__(self, db: AsyncSession):
        # Сохраняем сессию для использования в методах репозитория.
        self.db = db

    async def get_all(self) -> list[TagValue]:
        """Получить все теги, отсортированные по имени (tag_name)."""
        # SELECT * FROM tag_values ORDER BY tag_name — для стабильного порядка в таблице клиента.
        result = await self.db.execute(
            select(TagValue).order_by(TagValue.tag_name)
        )
        # Извлекаем список объектов TagValue.
        return result.scalars().all()


class TagService:
    """Бизнес-логика для работы с тегами.

    Тонкий слой над репозиторием — в данный момент не добавляет дополнительной логики,
    но изолирует роутеры от деталей доступа к данным.
    """

    def __init__(self, repo: TagRepository):
        # Принимаем репозиторий — зависимость инжектируется снаружи.
        self.repo = repo

    async def get_all(self) -> list[TagValue]:
        """Вернуть все теги с последними значениями (делегируем в репозиторий)."""
        return await self.repo.get_all()
