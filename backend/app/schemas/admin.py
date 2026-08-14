from pydantic import BaseModel, EmailStr, Field

from app.models.enums import AdminRole
from app.schemas.common import ORMModel


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminBootstrapRequest(BaseModel):
    secret: str
    email: EmailStr
    password: str = Field(min_length=12)


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminUserRead(ORMModel):
    id: int
    email: str
    role: AdminRole
    is_active: bool


class DashboardStats(BaseModel):
    total_users: int
    active_subscriptions: int
    active_devices: int
    online_servers: int
    online_peers: int
    revenue_last_30d: float
    open_support_tickets: int
