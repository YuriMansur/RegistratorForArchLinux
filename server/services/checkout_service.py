# HTTPException — для возврата HTTP 404 если испытание не найдено.
from fastapi import HTTPException
# select — для построения SQL SELECT запросов через SQLAlchemy ORM.
from sqlalchemy import select
# AsyncSession — асинхронная сессия для работы с БД в FastAPI эндпоинтах.
from sqlalchemy.ext.asyncio import AsyncSession

# ORM-модель таблицы checkouts.
from db.models import Checkout


class CheckoutRepository:
    """Слой доступа к данным — прямые запросы к таблице checkouts.

    Изолирует SQL-логику от бизнес-логики (CheckoutService).
    Принимает AsyncSession — инжектируется через FastAPI Depends(get_db).
    """

    def __init__(self, db: AsyncSession):
        # Сохраняем сессию для использования в методах репозитория.
        self.db = db

    async def get_all(self) -> list[Checkout]:
        """Получить все испытания, отсортированные от новых к старым."""
        # Строим SELECT * FROM checkouts ORDER BY started_at DESC.
        result = await self.db.execute(
            select(Checkout).order_by(Checkout.started_at.desc())
        )
        # scalars() извлекает объекты Checkout из строк результата.
        return result.scalars().all()

    async def get_by_id(self, checkout_id: int) -> Checkout | None:
        """Найти испытание по первичному ключу. Возвращает None если не найдено."""
        # db.get() использует кэш сессии и PRIMARY KEY — быстрее чем SELECT WHERE.
        return await self.db.get(Checkout, checkout_id)


class CheckoutService:
    """Бизнес-логика для работы с испытаниями.

    Добавляет проверки поверх репозитория (например, 404 если не найдено).
    Используется в роутерах через CheckoutService(CheckoutRepository(db)).
    """

    def __init__(self, repo: CheckoutRepository):
        # Принимаем репозиторий — зависимость инжектируется снаружи.
        self.repo = repo

    async def get_all(self) -> list[Checkout]:
        """Вернуть все испытания (делегируем в репозиторий)."""
        return await self.repo.get_all()

    async def get_by_id(self, checkout_id: int) -> Checkout:
        """Найти испытание по ID. Выбрасывает HTTP 404 если не найдено.

        Используется в эндпоинте экспорта — нельзя экспортировать несуществующее испытание.
        """
        # Запрашиваем у репозитория.
        checkout = await self.repo.get_by_id(checkout_id)
        if not checkout:
            # Испытание не найдено — возвращаем стандартный HTTP 404.
            raise HTTPException(status_code=404, detail="Checkout not found")
        return checkout
