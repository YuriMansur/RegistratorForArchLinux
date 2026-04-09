from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Checkout


class CheckoutRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[Checkout]:
        result = await self.db.execute(select(Checkout).order_by(Checkout.started_at.desc()))
        return result.scalars().all()

    async def get_by_id(self, checkout_id: int) -> Checkout | None:
        return await self.db.get(Checkout, checkout_id)


class CheckoutService:
    def __init__(self, repo: CheckoutRepository):
        self.repo = repo

    async def get_all(self) -> list[Checkout]:
        return await self.repo.get_all()

    async def get_by_id(self, checkout_id: int) -> Checkout:
        checkout = await self.repo.get_by_id(checkout_id)
        if not checkout:
            raise HTTPException(status_code=404, detail="Checkout not found")
        return checkout
