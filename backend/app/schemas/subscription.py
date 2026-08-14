from datetime import datetime

from pydantic import BaseModel

from app.models.enums import SubscriptionStatus
from app.schemas.common import ORMModel
from app.schemas.plan import PlanRead


class SubscriptionRead(ORMModel):
    id: int
    user_id: int
    plan: PlanRead
    status: SubscriptionStatus
    started_at: datetime | None
    expires_at: datetime | None
    auto_renew: bool


class SubscriptionCreateRequest(BaseModel):
    plan_id: int
    auto_renew: bool = False
    promo_code: str | None = None
