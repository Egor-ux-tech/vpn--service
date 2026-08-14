"""WireGuardProvider — talks to the `vpn-agent` service running on each VPNServer.

Every request is signed with an HMAC over the raw request body using the shared secret
configured for that server, so a compromised backend credential can't be replayed against
an unrelated agent, and the agent can reject tampered/forged requests. Requests to the agent
never include Postgres data beyond what the agent needs to act (device/peer identifiers,
desired state) and responses containing a private key are only ever read once, forwarded
immediately by the caller, and never logged (see `app/core/logging.py` redaction list).
"""

import time
from datetime import UTC, datetime

import httpx
import orjson

from app.core.errors import ExternalServiceError
from app.core.logging import get_logger
from app.core.metrics import VPN_PROVISIONING_ERRORS_TOTAL
from app.core.security import sign_hmac
from app.models.device import Device
from app.models.enums import VPNPeerStatus
from app.models.vpn_peer import VPNPeer
from app.models.vpn_server import VPNServer
from app.services.subscription_delivery.formatters.wireguard_formatter import (
    render_wireguard_config,
)
from app.services.vpn.provider import PeerProvisioningResult, PeerStatus

logger = get_logger(__name__)


class WireGuardProvider:
    def __init__(
        self, shared_secret: str, dns_servers: list[str], timeout_seconds: float = 10.0
    ) -> None:
        self._shared_secret = shared_secret
        self._dns = dns_servers
        self._timeout = timeout_seconds

    async def _request(
        self,
        server: VPNServer,
        method: str,
        path: str,
        payload: dict,
        *,
        params: dict[str, str] | None = None,
    ) -> dict:
        body = orjson.dumps(payload)
        signature = sign_hmac(body, self._shared_secret)
        headers = {
            "Content-Type": "application/json",
            "X-Signature": signature,
            "X-Timestamp": str(int(time.time())),
        }
        url = f"{server.agent_base_url.rstrip('/')}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method, url, content=body, headers=headers, params=params
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("vpn_agent_request_failed", server_id=server.id, path=path, error=str(exc))
            VPN_PROVISIONING_ERRORS_TOTAL.labels(operation=path).inc()
            raise ExternalServiceError(
                f"VPN agent request failed for server {server.id}",
                error_code="vpn_agent_unreachable",
            ) from exc
        return response.json() if response.content else {}

    async def create_peer(
        self, *, device: Device, server: VPNServer, assigned_ip: str
    ) -> PeerProvisioningResult:
        data = await self._request(
            server,
            "POST",
            "/peers",
            {"device_id": device.id, "assigned_ip": assigned_ip},
        )
        return PeerProvisioningResult(
            public_key=data["public_key"],
            private_key=data["private_key"],
            assigned_ip=data["assigned_ip"],
            server_public_key=server.public_key,
            server_endpoint=server.endpoint,
            dns=self._dns,
        )

    async def delete_peer(self, *, peer: VPNPeer, server: VPNServer) -> None:
        # WireGuard public keys are base64 and may contain '/', '+', '=' — an ASGI server
        # decodes percent-escaped slashes in the path before routing, so an encoded '/'
        # would be indistinguishable from a real path separator. The public key therefore
        # always travels as a query parameter, never as part of the URL path.
        await self._request(server, "DELETE", "/peers", {}, params={"public_key": peer.public_key})

    async def disable_peer(self, *, peer: VPNPeer, server: VPNServer) -> None:
        await self._request(
            server, "POST", "/peers/disable", {}, params={"public_key": peer.public_key}
        )

    async def enable_peer(self, *, peer: VPNPeer, server: VPNServer) -> None:
        await self._request(
            server, "POST", "/peers/enable", {}, params={"public_key": peer.public_key}
        )

    async def get_peer_status(self, *, peer: VPNPeer, server: VPNServer) -> PeerStatus:
        data = await self._request(
            server, "GET", "/peers/status", {}, params={"public_key": peer.public_key}
        )
        last_handshake = data.get("last_handshake_at")
        return PeerStatus(
            public_key=peer.public_key,
            status=VPNPeerStatus(data.get("status", peer.status.value)),
            last_handshake_at=datetime.fromisoformat(last_handshake) if last_handshake else None,
            rx_bytes=data.get("rx_bytes", 0),
            tx_bytes=data.get("tx_bytes", 0),
        )

    async def set_peer_allowed_ips(
        self, *, peer: VPNPeer, server: VPNServer, allowed_ips: list[str]
    ) -> None:
        await self._request(
            server,
            "POST",
            "/peers/allowed-ips",
            {"allowed_ips": allowed_ips},
            params={"public_key": peer.public_key},
        )

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
        # Rendering itself moved to render_wireguard_config (shared with the subscription
        # -delivery formatter, see app/services/subscription_delivery/formatters/
        # wireguard_formatter.py) — this method's own external behavior is unchanged,
        # including the empty-dns-falls-back-to-the-configured-default resolved here.
        return render_wireguard_config(
            private_key=private_key,
            assigned_ip=assigned_ip,
            server_public_key=server_public_key,
            server_endpoint=server_endpoint,
            allowed_ips=allowed_ips,
            dns=dns or self._dns,
        )


def utcnow() -> datetime:
    return datetime.now(UTC)
