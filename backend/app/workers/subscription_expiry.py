"""Subscription expiry sweep.

Run periodically (cron/systemd timer — see docs/deployment.md; no Celery/broker needed at
MVP scale). Each run: finds subscriptions whose `expires_at` has passed but are still marked
ACTIVE, flips them to EXPIRED, disables (not deletes) every VPN peer belonging to the user so
a later renewal can re-enable the same peers instead of re-provisioning, records an audit log
entry, and notifies the user — all within one lifecycle step so a partial failure (e.g.
notification delivery) never leaves the subscription itself in an inconsistent state.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.models.subscription import Subscription
from app.services.audit_service import AuditService
from app.services.device_service import DeviceService
from app.services.notifications.provider import NotificationProvider
from app.services.subscription_service import SubscriptionService

logger = get_logger(__name__)


@dataclass(slots=True)
class ExpirySummary:
    expired_subscription_ids: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.expired_subscription_ids)


class SubscriptionExpiryWorker:
    def __init__(
        self,
        subscription_service: SubscriptionService,
        device_service: DeviceService,
        audit_service: AuditService,
        notifier: NotificationProvider,
    ) -> None:
        self._subscriptions = subscription_service
        self._devices = device_service
        self._audit = audit_service
        self._notifier = notifier

    async def _process_one(self, subscription: Subscription) -> None:
        plan_name = subscription.plan.name
        user = subscription.user

        await self._subscriptions.expire(subscription)
        await self._devices.disable_all_for_user(subscription.user_id)
        await self._audit.record(
            admin_id=None,
            action="subscription.expired",
            target_type="subscription",
            target_id=str(subscription.id),
            metadata={"user_id": subscription.user_id, "plan": plan_name},
        )

        message = (
            f"⏰ Ваша подписка «{plan_name}» истекла. VPN-доступ приостановлен.\n"
            "Продлите подписку в разделе «Подписка», чтобы возобновить доступ — "
            "все ваши устройства будут включены автоматически."
        )
        await self._notifier.notify(telegram_id=user.telegram_id, message=message)

        logger.info(
            "subscription_expired", subscription_id=subscription.id, user_id=subscription.user_id
        )

    async def run_once(self, *, as_of: datetime | None = None) -> ExpirySummary:
        expired = await self._subscriptions.list_expired(as_of or datetime.now(UTC))
        summary = ExpirySummary()
        for subscription in expired:
            await self._process_one(subscription)
            summary.expired_subscription_ids.append(subscription.id)
        if summary.count:
            logger.info("expiry_sweep_complete", expired_count=summary.count)
        return summary
