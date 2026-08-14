from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.enums import SubscriptionStatus
from app.models.subscription import Subscription
from app.repositories.base import BaseRepository


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    async def get(self, id_: int) -> Subscription | None:
        # `plan` is eager-loaded because callers routinely access it synchronously (e.g.
        # SubscriptionRead serialization, activation logic) — a bare lazy-load there raises
        # MissingGreenlet outside of an awaited SQLAlchemy call.
        return await self.session.get(Subscription, id_, options=[selectinload(Subscription.plan)])

    async def get_active_for_user(self, user_id: int) -> Subscription | None:
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.expires_at.desc())
            .options(selectinload(Subscription.plan))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_expired(self, as_of: datetime) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at.is_not(None),
                Subscription.expires_at <= as_of,
            )
            # `user` is eager-loaded alongside `plan` because the expiry worker needs the
            # owning user's telegram_id to send a notification, right after expiring.
            .options(selectinload(Subscription.plan), selectinload(Subscription.user))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_user(self, user_id: int) -> list[Subscription]:
        stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .options(selectinload(Subscription.plan))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
