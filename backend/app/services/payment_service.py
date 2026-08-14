from datetime import UTC, datetime
from decimal import Decimal

from app.core.errors import NotFoundError, UnauthorizedError, ValidationAppError
from app.core.logging import get_logger
from app.core.security import generate_internal_id
from app.models.enums import PaymentStatus
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.promo_code import PromoCodeRedemption
from app.models.user import User
from app.repositories.payment_repository import PaymentRepository
from app.repositories.promo_code_repository import (
    PromoCodeRedemptionRepository,
    PromoCodeRepository,
)
from app.services.payments.provider import PaymentIntentStatus, PaymentProvider
from app.services.subscription_service import SubscriptionService

logger = get_logger(__name__)


def _apply_discount(amount: Decimal, discount_type: str, discount_value: Decimal) -> Decimal:
    if discount_type == "percent":
        discounted = amount * (Decimal(100) - discount_value) / Decimal(100)
    else:
        discounted = amount - discount_value
    return max(discounted, Decimal("0"))


class PaymentService:
    def __init__(
        self,
        payment_repository: PaymentRepository,
        promo_code_repository: PromoCodeRepository,
        promo_redemption_repository: PromoCodeRedemptionRepository,
        subscription_service: SubscriptionService,
        provider: PaymentProvider,
        provider_name: str,
    ) -> None:
        self._payments = payment_repository
        self._promo_codes = promo_code_repository
        self._promo_redemptions = promo_redemption_repository
        self._subscriptions = subscription_service
        self._provider = provider
        self._provider_name = provider_name

    async def create_payment(
        self, *, user: User, plan: Plan, promo_code: str | None = None
    ) -> tuple[Payment, str | None]:
        amount = Decimal(str(plan.price))
        promo = None
        if promo_code:
            promo = await self._promo_codes.get_by_code(promo_code)
            if promo is None or not promo.active:
                raise ValidationAppError("Invalid promo code", error_code="invalid_promo_code")
            now = datetime.now(UTC)
            if promo.valid_from and now < promo.valid_from:
                raise ValidationAppError("Promo code not yet valid", error_code="promo_not_active")
            if promo.valid_until and now > promo.valid_until:
                raise ValidationAppError("Promo code expired", error_code="promo_expired")
            if promo.max_uses is not None and promo.used_count >= promo.max_uses:
                raise ValidationAppError("Promo code exhausted", error_code="promo_exhausted")
            if await self._promo_redemptions.get(promo.id, user.id) is not None:
                raise ValidationAppError(
                    "Promo code already used by this user", error_code="promo_already_used"
                )
            amount = _apply_discount(
                amount, promo.discount_type.value, Decimal(str(promo.discount_value))
            )

        idempotency_key = generate_internal_id("pay_")
        subscription = await self._subscriptions.create_pending(
            user=user, plan=plan, auto_renew=False
        )

        intent = await self._provider.create_payment(
            amount=amount,
            currency=plan.currency,
            description=f"Subscription: {plan.name}",
            idempotency_key=idempotency_key,
        )

        payment = Payment(
            user_id=user.id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            provider=self._provider_name,
            external_payment_id=intent.external_payment_id,
            idempotency_key=idempotency_key,
            amount=amount,
            currency=plan.currency,
            status=PaymentStatus.PENDING,
            promo_code_id=promo.id if promo else None,
            metadata_json={},
        )
        self._payments.add(payment)
        await self._payments.flush()
        return payment, intent.checkout_url

    async def handle_webhook(self, *, raw_body: bytes, signature: str) -> Payment:
        if not self._provider.verify_webhook_signature(raw_body=raw_body, signature=signature):
            raise UnauthorizedError("Invalid webhook signature", error_code="invalid_signature")

        event = self._provider.parse_webhook(raw_body=raw_body)
        payment = await self._payments.get_by_provider_external_id(
            self._provider_name, event.external_payment_id
        )
        if payment is None:
            raise NotFoundError(
                "Payment not found for webhook event", error_code="payment_not_found"
            )

        # Idempotency: a webhook may be delivered more than once. If we've already recorded
        # a terminal status for this payment, acknowledge without re-applying side effects.
        if payment.status in (
            PaymentStatus.SUCCEEDED,
            PaymentStatus.REFUNDED,
            PaymentStatus.CANCELLED,
        ):
            logger.info("webhook_already_processed", payment_id=payment.id, status=payment.status)
            return payment

        if event.status is PaymentIntentStatus.SUCCEEDED:
            payment.status = PaymentStatus.SUCCEEDED
            if payment.subscription_id is None:
                raise ValidationAppError(
                    "Payment has no associated subscription",
                    error_code="payment_missing_subscription",
                )
            subscription = await self._subscriptions.get(payment.subscription_id)
            plan = subscription.plan
            await self._subscriptions.activate(subscription, plan)

            if payment.promo_code_id:
                promo = await self._promo_codes.get(payment.promo_code_id)
                if promo is not None:
                    promo.used_count += 1
                    self._promo_redemptions.add(
                        PromoCodeRedemption(
                            promo_code_id=promo.id,
                            user_id=payment.user_id,
                            payment_id=payment.id,
                            redeemed_at=datetime.now(UTC),
                        )
                    )
        elif event.status is PaymentIntentStatus.FAILED:
            payment.status = PaymentStatus.FAILED

        await self._payments.flush()
        return payment

    async def refund(self, payment: Payment) -> Payment:
        if payment.status is not PaymentStatus.SUCCEEDED:
            raise ValidationAppError(
                "Only succeeded payments can be refunded", error_code="payment_not_refundable"
            )
        ok = await self._provider.refund_payment(payment.external_payment_id or "")
        if ok:
            payment.status = PaymentStatus.REFUNDED
        return payment
