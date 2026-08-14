"""Payment transport abstraction. MVP ships a `MockPaymentProvider` for local dev/testing;
a real gateway (YooKassa, Cryptomus, Stripe, ...) is a new adapter implementing the same
`PaymentProvider` protocol — no service/API code above this layer needs to change.

A subscription is only ever activated from `PaymentService.handle_webhook` after a provider
confirms `PaymentIntentStatus.SUCCEEDED` — never from the "user pressed pay" client action.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class PaymentIntentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PaymentIntent:
    external_payment_id: str
    checkout_url: str | None
    status: PaymentIntentStatus


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    external_payment_id: str
    status: PaymentIntentStatus
    amount: Decimal
    currency: str
    raw_payload: dict


class PaymentProvider(Protocol):
    async def create_payment(
        self, *, amount: Decimal, currency: str, description: str, idempotency_key: str
    ) -> PaymentIntent: ...

    async def check_payment(self, external_payment_id: str) -> PaymentIntentStatus: ...

    def verify_webhook_signature(self, *, raw_body: bytes, signature: str) -> bool: ...

    def parse_webhook(self, *, raw_body: bytes) -> WebhookEvent: ...

    async def refund_payment(self, external_payment_id: str) -> bool: ...
