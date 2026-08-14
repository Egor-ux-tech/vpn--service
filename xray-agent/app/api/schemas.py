from datetime import datetime

from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    uuid: str
    device_id: int
    flow: str = "xtls-rprx-vision"


class RotateUserRequest(BaseModel):
    new_uuid: str


class UserResponse(BaseModel):
    uuid: str
    device_id: int
    flow: str
    created_at: datetime
    rotated_at: datetime | None


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    xray_reachable: bool


class StatusResponse(BaseModel):
    status: str
    xray_reachable: bool
    active_user_count: int
    live_user_count: int | None
    last_reconciliation_at: datetime | None
