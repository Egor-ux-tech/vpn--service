from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class PlanCreate(BaseModel):
    name: str
    slug: str
    price: Decimal = Field(ge=0)
    currency: str = "RUB"
    duration_days: int = Field(gt=0)
    max_devices: int = Field(gt=0, default=1)
    max_speed_mbps: int | None = None
    active: bool = True


class PlanUpdate(BaseModel):
    name: str | None = None
    price: Decimal | None = None
    duration_days: int | None = None
    max_devices: int | None = None
    max_speed_mbps: int | None = None
    active: bool | None = None


class PlanRead(ORMModel):
    id: int
    name: str
    slug: str
    price: Decimal
    currency: str
    duration_days: int
    max_devices: int
    max_speed_mbps: int | None
    active: bool
