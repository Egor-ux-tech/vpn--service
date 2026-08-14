from pydantic import BaseModel

from app.models.enums import VPNServerStatus


class VLESSServerCreate(BaseModel):
    name: str
    country: str
    city: str | None = None
    hostname: str
    capacity: int = 100
    xray_agent_base_url: str
    port: int = 443
    reality_public_key: str
    reality_short_ids: list[str] = [""]
    sni: str
    fingerprint: str = "chrome"
    flow: str = "xtls-rprx-vision"
    network_type: str = "tcp"


class VLESSServerUpdate(BaseModel):
    status: VPNServerStatus | None = None
    capacity: int | None = None
    name: str | None = None
    xray_agent_base_url: str | None = None
    port: int | None = None
    reality_public_key: str | None = None
    reality_short_ids: list[str] | None = None
    sni: str | None = None
    fingerprint: str | None = None
    flow: str | None = None
    network_type: str | None = None


class VLESSServerRead(BaseModel):
    id: int
    name: str
    country: str
    city: str | None
    hostname: str
    status: VPNServerStatus
    capacity: int
    current_load: int
    xray_agent_base_url: str
    port: int
    reality_public_key: str
    reality_short_ids: list[str]
    sni: str
    fingerprint: str
    flow: str
    network_type: str
