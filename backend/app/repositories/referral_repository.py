from sqlalchemy import select

from app.models.referral import Referral
from app.repositories.base import BaseRepository


class ReferralRepository(BaseRepository[Referral]):
    model = Referral

    async def get_by_referred(self, referred_user_id: int) -> Referral | None:
        stmt = select(Referral).where(Referral.referred_user_id == referred_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_referrer(self, referrer_user_id: int) -> list[Referral]:
        stmt = select(Referral).where(Referral.referrer_user_id == referrer_user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
