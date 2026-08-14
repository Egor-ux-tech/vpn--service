from datetime import UTC, datetime

from app.core.errors import ConflictError, ValidationAppError
from app.models.referral import Referral
from app.repositories.referral_repository import ReferralRepository


class ReferralService:
    def __init__(self, referral_repository: ReferralRepository) -> None:
        self._referrals = referral_repository

    async def register(self, *, referrer_user_id: int, referred_user_id: int) -> Referral:
        if referrer_user_id == referred_user_id:
            raise ValidationAppError("Cannot refer yourself", error_code="self_referral")
        if await self._referrals.get_by_referred(referred_user_id) is not None:
            raise ConflictError("User was already referred", error_code="already_referred")
        referral = Referral(
            referrer_user_id=referrer_user_id,
            referred_user_id=referred_user_id,
            reward_applied=False,
            created_at=datetime.now(UTC),
        )
        self._referrals.add(referral)
        await self._referrals.flush()
        return referral
