from pydantic import BaseModel

from app.models.enums import RouteType, RoutingMode
from app.schemas.common import ORMModel


class RoutingCategoryCreate(BaseModel):
    name: str
    description: str | None = None


class RoutingCategoryRead(ORMModel):
    id: int
    name: str
    description: str | None
    enabled: bool


class RoutingRuleCreate(BaseModel):
    category_id: int
    domain: str
    route_type: RouteType = RouteType.VPN
    enabled: bool = True


class RoutingRuleRead(ORMModel):
    id: int
    category_id: int
    domain: str
    route_type: RouteType
    enabled: bool


class UserRoutingModeUpdate(BaseModel):
    mode: RoutingMode


class UserCategoryPreferenceUpdate(BaseModel):
    category_id: int
    enabled: bool


class UserCustomDomainCreate(BaseModel):
    domain: str
    route_type: RouteType = RouteType.VPN


class UserRoutingSettingsRead(BaseModel):
    mode: RoutingMode
    categories: list[RoutingCategoryRead]
    enabled_category_ids: list[int]
    custom_domains: list[str]
