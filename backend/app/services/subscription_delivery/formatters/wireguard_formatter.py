"""`render_wireguard_config` is the exact rendering logic that used to live inline in
`WireGuardProvider.build_client_config` — moved here so it has one home shared by both
call sites: device provisioning/reissue (has a real private key, used once — see
DeviceService) and subscription-link delivery (never has one — see WireGuardFormatter
below). `WireGuardProvider.build_client_config` now delegates to this function; nothing
about its own external behavior changed.
"""

from app.models.device import Device
from app.models.vpn_peer import VPNPeer
from app.models.vpn_profile import VPNProfile
from app.models.vpn_server import VPNServer

_NO_PRIVATE_KEY_COMMENT = (
    "# PrivateKey intentionally omitted: this service never stores WireGuard private\n"
    "# keys (see docs/wireguard.md), so a subscription link fetched after the device was\n"
    '# provisioned cannot include one. Use "Reissue" in the bot for a complete, working\n'
    "# config with a fresh private key.\n"
)


def render_wireguard_config(
    *,
    private_key: str | None,
    assigned_ip: str,
    server_public_key: str,
    server_endpoint: str,
    allowed_ips: list[str],
    dns: list[str],
) -> str:
    """Pure — no network calls, no provider/service state. `dns` must already be the
    fully-resolved list the caller wants rendered (WireGuardProvider.build_client_config
    resolves its own empty-list-falls-back-to-configured-default behavior *before* calling
    this, so that behavior is unchanged for existing callers)."""
    allowed = ", ".join(allowed_ips) if allowed_ips else "0.0.0.0/0, ::/0"
    dns_line = ", ".join(dns)
    private_key_section = (
        f"PrivateKey = {private_key}\n" if private_key is not None else _NO_PRIVATE_KEY_COMMENT
    )
    return (
        "[Interface]\n"
        f"{private_key_section}"
        f"Address = {assigned_ip}\n"
        f"DNS = {dns_line}\n\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {server_endpoint}\n"
        f"AllowedIPs = {allowed}\n"
        "PersistentKeepalive = 25\n"
    )


class WireGuardFormatter:
    """Renders a device's *current* peer state as a WireGuard config for subscription-link
    delivery (GET /sub/{token}). Deliberately incomplete relative to what provisioning
    returns: no private key (see render_wireguard_config's comment) — this is a known,
    documented Phase 1 limitation, not a bug. See docs/subscription-delivery.md for the
    two options (persist an encrypted key, or move key generation to the client) that would
    resolve it, both explicitly out of scope for this phase.
    """

    format_id = "wireguard"
    content_type = "text/plain; charset=utf-8"

    async def render(
        self,
        *,
        device: Device,  # noqa: ARG002 -- part of the shared formatter signature; unused here
        peer: VPNPeer,
        server: VPNServer,
        profile: VPNProfile | None,
    ) -> bytes:
        allowed_ips = profile.allowed_ips if profile is not None else ["0.0.0.0/0", "::/0"]
        dns = profile.dns if profile is not None else []
        text = render_wireguard_config(
            private_key=None,
            assigned_ip=peer.assigned_ip,
            server_public_key=server.public_key,
            server_endpoint=server.endpoint,
            allowed_ips=allowed_ips,
            dns=dns,
        )
        return text.encode("utf-8")
