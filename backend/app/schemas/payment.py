from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import PaymentStatus
from app.schemas.common import ORMModel


class PaymentCreateRequest(BaseModel):
    plan_id: int
    promo_code: str | None = None


class PaymentCreateResponse(BaseModel):
    payment_id: int
    checkout_url: str | None
    status: PaymentStatus


class PaymentRead(ORMModel):
    id: int
    user_id: int
    plan_id: int
    provider: str
    amount: Decimal
    currency: str
    status: PaymentStatus


class WebhookAck(BaseModel):
    received: bool = True
