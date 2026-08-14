from datetime import UTC, datetime, timedelta

from app.core.errors import NotFoundError, ValidationAppError
from app.models.enums import SubscriptionStatus
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.repositories.subscription_repository import SubscriptionRepository


class SubscriptionService:
    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        self._subscriptions = subscription_repository

    async def get(self, subscription_id: int) -> Subscription:
        subscription = await self._subscriptions.get(subscription_id)
        if subscription is None:
            raise NotFoundError("Subscription not found", error_code="subscription_not_found")
        return subscription

    async def get_active_for_user(self, user_id: int) -> Subscription | None:
        return await self._subscriptions.get_active_for_user(user_id)

    async def list_for_user(self, user_id: int) -> list[Subscription]:
        return await self._subscriptions.list_for_user(user_id)

    async def create_pending(self, *, user: User, plan: Plan, auto_renew: bool) -> Subscription:
        if not plan.active:
            raise ValidationAppError("Plan is not active", error_code="plan_inactive")
        subscription = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.PENDING,
            auto_renew=auto_renew,
        )
        self._subscriptions.add(subscription)
        await self._subscriptions.flush()
        return subscription

    async def activate(self, subscription: Subscription, plan: Plan) -> Subscription:
        """Extends from `now` normally, or from the current expiry if the subscription is
        already active and being renewed early — a renewal never shortens remaining time."""
        now = datetime.now(UTC)
        base = (
            subscription.expires_at
            if (
                subscription.status == SubscriptionStatus.ACTIVE
                and subscription.expires_at is not None
                and subscription.expires_at > now
            )
            else now
        )

        subscription.status = SubscriptionStatus.ACTIVE
        subscription.started_at = subscription.started_at or now
        subscription.expires_at = base + timedelta(days=plan.duration_days)
        return subscription

    async def cancel(self, subscription: Subscription) -> Subscription:
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.auto_renew = False
        return subscription

    async def expire(self, subscription: Subscription) -> Subscription:
        subscription.status = SubscriptionStatus.EXPIRED
        return subscription

    async def list_expired(self, as_of: datetime | None = None) -> list[Subscription]:
        return await self._subscriptions.list_expired(as_of or datetime.now(UTC))
