"""A safe, fully local `PaymentProvider` — no external network calls. Used for local
development/CI and as a manual/offline provider (e.g. staff confirming a bank transfer).
Never enable `PAYMENT_PROVIDER=mock` in production for real money flows.
"""

from decimal import Decimal

import orjson

from app.core.security import generate_internal_id, sign_hmac, verify_hmac
from app.services.payments.provider import PaymentIntent, PaymentIntentStatus, WebhookEvent


class MockPaymentProvider:
    def __init__(self, webhook_secret: str) -> None:
        self._webhook_secret = webhook_secret

    async def create_payment(
        self, *, amount: Decimal, currency: str, description: str, idempotency_key: str
    ) -> PaymentIntent:
        external_id = generate_internal_id("mock_")
        return PaymentIntent(
            external_payment_id=external_id,
            checkout_url=f"https://mock-payments.local/pay/{external_id}",
            status=PaymentIntentStatus.PENDING,
        )

    async def check_payment(self, external_payment_id: str) -> PaymentIntentStatus:
        return PaymentIntentStatus.SUCCEEDED

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool:
        return verify_hmac(raw_body, self._webhook_secret, signature)

    def parse_webhook(self, *, raw_body: bytes) -> WebhookEvent:
        payload = orjson.loads(raw_body)
        return WebhookEvent(
            external_payment_id=payload["external_payment_id"],
            status=PaymentIntentStatus(payload["status"]),
            amount=payload["amount"],
            currency=payload.get("currency", "RUB"),
            raw_payload=payload,
        )

    async def refund_payment(self, external_payment_id: str) -> bool:
        return True

    def sign_payload(self, payload: dict) -> str:
        """Test/dev helper to produce a validly-signed webhook body."""
        return sign_hmac(orjson.dumps(payload), self._webhook_secret)
