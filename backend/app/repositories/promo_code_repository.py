from sqlalchemy import select

from app.models.promo_code import PromoCode, PromoCodeRedemption
from app.repositories.base import BaseRepository


class PromoCodeRepository(BaseRepository[PromoCode]):
    model = PromoCode

    async def get_by_code(self, code: str) -> PromoCode | None:
        stmt = select(PromoCode).where(PromoCode.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class PromoCodeRedemptionRepository(BaseRepository[PromoCodeRedemption]):
    model = PromoCodeRedemption

    async def get(self, promo_code_id: int, user_id: int) -> PromoCodeRedemption | None:  # type: ignore[override]
        stmt = select(PromoCodeRedemption).where(
            PromoCodeRedemption.promo_code_id == promo_code_id,
            PromoCodeRedemption.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
