"""VPN transport abstraction.

`VPNProvider` is the contract the rest of the backend depends on. `WireGuardProvider`
(see `wireguard_provider.py`) is the MVP implementation, talking to a `vpn-agent` process
running on each `VPNServer`. A future transport (e.g. AmneziaWG, OpenVPN, a multi-hop
provider) can be added by implementing this same interface — no other backend code needs
to change.

Private keys are handled as ephemeral values only: they exist in a `PeerProvisioningResult`
returned once from `create_peer`, are forwarded to the user, and are never persisted or
logged by this layer.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models.device import Device
from app.models.enums import VPNPeerStatus
from app.models.vpn_peer import VPNPeer
from app.models.vpn_server import VPNServer


@dataclass(frozen=True, slots=True)
class PeerProvisioningResult:
    public_key: str
    private_key: str  # ephemeral — caller must forward and must never persist/log this
    assigned_ip: str
    server_public_key: str
    server_endpoint: str
    dns: list[str]


@dataclass(frozen=True, slots=True)
class PeerStatus:
    public_key: str
    status: VPNPeerStatus
    last_handshake_at: datetime | None
    rx_bytes: int
    tx_bytes: int


class VPNProvider(Protocol):
    async def create_peer(
        self, *, device: Device, server: VPNServer, assigned_ip: str
    ) -> PeerProvisioningResult:
        """Generate a keypair (on the server) and register a new peer at `assigned_ip`
        (allocated by the caller from `server.internal_network` — see `ip_allocator.py`, the
        control plane owns IP bookkeeping so it stays a single source of truth). Returns the
        private key exactly once — the caller is responsible for delivering it to the user
        and must not store or log it."""
        ...

    async def delete_peer(self, *, peer: VPNPeer, server: VPNServer) -> None: ...

    async def disable_peer(self, *, peer: VPNPeer, server: VPNServer) -> None: ...

    async def enable_peer(self, *, peer: VPNPeer, server: VPNServer) -> None: ...

    async def get_peer_status(self, *, peer: VPNPeer, server: VPNServer) -> PeerStatus: ...

    async def set_peer_allowed_ips(
        self, *, peer: VPNPeer, server: VPNServer, allowed_ips: list[str]
    ) -> None:
        """Push an updated AllowedIPs set for split tunneling (Smart VPN)."""
        ...

    def build_client_config(
        self,
        *,
        private_key: str,
        assigned_ip: str,
        server_public_key: str,
        server_endpoint: str,
        allowed_ips: list[str],
        dns: list[str],
    ) -> str:
        """Render a standard WireGuard `.conf` file. Pure/local — no network call."""
        ...
