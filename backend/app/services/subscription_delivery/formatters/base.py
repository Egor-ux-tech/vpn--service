"""The extension point for adding a new subscription-delivery client/format later (Happ,
v2rayNG, clash, sing-box, ...) without touching the token/security/delivery layers above
it — see docs/subscription-delivery.md. Only WireGuardFormatter exists today.
"""

from typing import Protocol

from app.models.device import Device
from app.models.vpn_peer import VPNPeer
from app.models.vpn_profile import VPNProfile
from app.models.vpn_server import VPNServer


class SubscriptionFormatter(Protocol):
    format_id: str
    content_type: str

    async def render(
        self,
        *,
        device: Device,
        peer: VPNPeer,
        server: VPNServer,
        profile: VPNProfile | None,
    ) -> bytes:
        """Pure/local — no network calls, no DB writes. All data the formatter needs is
        passed in by SubscriptionDeliveryService, which already did the authorization
        checks; a formatter never decides *whether* to render, only *how*."""
        ...
