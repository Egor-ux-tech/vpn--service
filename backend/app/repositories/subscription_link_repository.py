from sqlalchemy import select

from app.models.subscription_link import SubscriptionLink
from app.repositories.base import BaseRepository


class SubscriptionLinkRepository(BaseRepository[SubscriptionLink]):
    model = SubscriptionLink

    async def get_for_device(self, device_id: int) -> SubscriptionLink | None:
        stmt = select(SubscriptionLink).where(SubscriptionLink.device_id == device_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_token_hash(self, token_hash: str) -> SubscriptionLink | None:
        stmt = select(SubscriptionLink).where(SubscriptionLink.token_hash == token_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
