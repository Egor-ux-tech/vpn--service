from datetime import datetime

from pydantic import BaseModel

from app.models.enums import DeviceStatus
from app.schemas.common import ORMModel


class DeviceCreateRequest(BaseModel):
    name: str
    server_id: int | None = None


class DeviceRead(ORMModel):
    id: int
    name: str
    status: DeviceStatus
    public_key: str | None
    assigned_ip: str | None
    server_id: int | None
    created_at: datetime
    last_seen: datetime | None


class DeviceProvisioningResult(BaseModel):
    device: DeviceRead
    config_text: str
    qr_code_base64: str
