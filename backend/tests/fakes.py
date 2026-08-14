"""In-memory test doubles — no network calls, no real WireGuard/Postgres involved."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.models.device import Device
from app.models.enums import VPNPeerStatus
from app.models.vpn_peer import VPNPeer
from app.models.vpn_server import VPNServer
from app.services.vpn.provider import PeerProvisioningResult, PeerStatus


@dataclass
class FakeVPNProvider:
    """Stands in for WireGuardProvider in tests: generates fake keys locally instead of
    calling a real vpn-agent over HTTP."""

    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    enabled: list[str] = field(default_factory=list)
    _counter: int = 0

    async def create_peer(
        self, *, device: Device, server: VPNServer, assigned_ip: str
    ) -> PeerProvisioningResult:
        self._counter += 1
        public_key = f"fake-pub-{self._counter}"
        self.created.append(public_key)
        return PeerProvisioningResult(
            public_key=public_key,
            private_key=f"fake-priv-{self._counter}",
            assigned_ip=assigned_ip,
            server_public_key=server.public_key,
            server_endpoint=server.endpoint,
            dns=["1.1.1.1"],
        )

    async def delete_peer(self, *, peer: VPNPeer, server: VPNServer) -> None:
        self.deleted.append(peer.public_key)

    async def disable_peer(self, *, peer: VPNPeer, server: VPNServer) -> None:
        self.disabled.append(peer.public_key)

    async def enable_peer(self, *, peer: VPNPeer, server: VPNServer) -> None:
        self.enabled.append(peer.public_key)

    async def get_peer_status(self, *, peer: VPNPeer, server: VPNServer) -> PeerStatus:
        return PeerStatus(
            public_key=peer.public_key,
            status=VPNPeerStatus.ACTIVE,
            last_handshake_at=datetime.now(UTC),
            rx_bytes=0,
            tx_bytes=0,
        )

    async def set_peer_allowed_ips(
        self, *, peer: VPNPeer, server: VPNServer, allowed_ips: list[str]
    ) -> None:
        return None

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
        allowed = ", ".join(allowed_ips) if allowed_ips else "0.0.0.0/0"
        return (
            f"[Interface]\nPrivateKey = {private_key}\nAddress = {assigned_ip}\n\n"
            f"[Peer]\nPublicKey = {server_public_key}\nEndpoint = {server_endpoint}\n"
            f"AllowedIPs = {allowed}\n"
        )


class FakeDomainResolver:
    """Deterministic resolver — no real DNS lookups."""

    def __init__(self, records: dict[str, list[str]]) -> None:
        self._records = records

    async def resolve(self, domain: str, fallback_ips: list[str] | None = None) -> list[str]:
        return self._records.get(domain, [])
