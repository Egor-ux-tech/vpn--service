from pydantic import BaseModel

from app.models.enums import VPNServerStatus
from app.schemas.common import ORMModel


class VPNServerCreate(BaseModel):
    name: str
    country: str
    city: str | None = None
    hostname: str
    agent_base_url: str
    public_key: str
    endpoint: str
    listen_port: int = 51820
    internal_network: str
    capacity: int = 100


class VPNServerUpdate(BaseModel):
    status: VPNServerStatus | None = None
    capacity: int | None = None
    name: str | None = None


class VPNServerRead(ORMModel):
    id: int
    name: str
    country: str
    city: str | None
    hostname: str
    endpoint: str
    status: VPNServerStatus
    capacity: int
    current_load: int


class VPNServerHealth(BaseModel):
    server_id: int
    status: VPNServerStatus
    peer_count: int
    latency_ms: float | None = None
