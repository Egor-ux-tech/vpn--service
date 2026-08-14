from sqlalchemy import select

from app.models.payment import Payment
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        stmt = select(Payment).where(Payment.idempotency_key == idempotency_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider_external_id(
        self, provider: str, external_payment_id: str
    ) -> Payment | None:
        stmt = select(Payment).where(
            Payment.provider == provider, Payment.external_payment_id == external_payment_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: int) -> list[Payment]:
        stmt = select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, offset: int = 0, limit: int = 50) -> list[Payment]:
        stmt = select(Payment).order_by(Payment.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
