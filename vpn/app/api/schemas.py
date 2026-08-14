from datetime import datetime

from pydantic import BaseModel


class CreatePeerRequest(BaseModel):
    device_id: int
    assigned_ip: str


class CreatePeerResponse(BaseModel):
    public_key: str
    private_key: str
    assigned_ip: str


class AllowedIPsUpdateRequest(BaseModel):
    allowed_ips: list[str]


class PeerStatusResponse(BaseModel):
    public_key: str
    status: str
    last_handshake_at: datetime | None
    rx_bytes: int
    tx_bytes: int


class HealthResponse(BaseModel):
    status: str
    interface: str
    peer_count: int
