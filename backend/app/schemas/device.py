from datetime import datetime

from pydantic import BaseModel

from app.models.enums import DeviceStatus, VPNProtocol
from app.schemas.common import ORMModel


class DeviceCreateRequest(BaseModel):
    name: str
    server_id: int | None = None
    protocol: VPNProtocol = VPNProtocol.WIREGUARD


class DeviceRead(ORMModel):
    id: int
    name: str
    status: DeviceStatus
    protocol: VPNProtocol
    public_key: str | None
    assigned_ip: str | None
    server_id: int | None
    created_at: datetime
    last_seen: datetime | None


class DeviceProvisioningResult(BaseModel):
    device: DeviceRead
    # None for VLESS devices — there is no separate downloadable config, only the
    # subscription link (below). See ProvisionedDevice's docstring in device_service.py.
    config_text: str | None
    qr_code_base64: str | None
    # Only set when provisioning a new device — see ProvisionedDevice's docstring in
    # device_service.py for why reissue() can never populate this.
    subscription_url: str | None = None
    subscription_qr_code_base64: str | None = None
