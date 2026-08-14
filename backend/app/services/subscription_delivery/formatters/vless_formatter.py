"""`render_vless_uri` renders a single `vless://` share link — the exact grammar
confirmed against Happ's official example during the VLESS/Happ compatibility research
spike (see docs/vless.md). `VLESSFormatter` renders one such line per active
`VLESSCredential` a device has (see app/models/vless_credential.py — MVP always
provisions exactly one, but multi-node support means a device *can* have more, and the
subscription body must reflect all of them, not just the first).

Deliberately excludes:
- `node_id` — not part of the confirmed grammar; nothing in this architecture needs the
  client to know it.
- `xtls=2` / `sid` — `sid` is omittable client-side because every node's Reality config
  ships a single empty shortId entry (see infrastructure/ansible/roles/xray); `xtls=2`'s
  meaning/necessity was never confirmed against official sources, so it is not invented.
- Smart Routing — not implemented yet (see docs/vless.md).
"""

from urllib.parse import quote

from app.models.device import Device
from app.models.vless_credential import VLESSCredential
from app.models.vless_server_config import VLESSServerConfig
from app.models.vpn_server import VPNServer


def render_vless_uri(
    *,
    uuid: str,
    host: str,
    port: int,
    sni: str,
    reality_public_key: str,
    fingerprint: str,
    flow: str,
    network_type: str,
    name: str,
) -> str:
    """Pure — no network calls, no DB access. `name` becomes the URI fragment (the
    label a client shows the user) and is percent-encoded; every other value is a
    plain ASCII identifier/hostname that doesn't need encoding, but is quoted anyway
    for defense in depth against a device name or SNI containing unexpected characters."""
    query = (
        f"encryption=none&security=reality&sni={quote(sni, safe='')}"
        f"&pbk={quote(reality_public_key, safe='')}&fp={quote(fingerprint, safe='')}"
        f"&type={quote(network_type, safe='')}&flow={quote(flow, safe='')}"
    )
    fragment = quote(name, safe="")
    return f"vless://{uuid}@{host}:{port}?{query}#{fragment}"


class VLESSFormatter:
    """Renders a device's currently-active VLESS credential(s) as subscription-body
    `vless://` lines — one per credential, in the order the delivery service supplies
    them. Deliberately does not implement the same `SubscriptionFormatter` Protocol as
    `WireGuardFormatter`: that Protocol's `render(peer, server, profile)` shape is
    single-peer, WireGuard-specific, and forcing VLESS's multi-credential rendering
    into it would either bloat the shared Protocol or silently drop credentials past
    the first — see SubscriptionDeliveryService.deliver, which dispatches to this
    formatter through its own dedicated path instead.
    """

    format_id = "vless"
    content_type = "text/plain; charset=utf-8"

    async def render(
        self,
        *,
        device: Device,
        items: list[tuple[VLESSCredential, VPNServer, VLESSServerConfig]],
    ) -> bytes:
        lines = [
            render_vless_uri(
                uuid=credential.uuid,
                host=server.hostname,
                port=server_config.port,
                sni=server_config.sni,
                reality_public_key=server_config.reality_public_key,
                fingerprint=server_config.fingerprint,
                flow=server_config.flow,
                network_type=server_config.network_type,
                name=device.name,
            )
            for credential, server, server_config in items
        ]
        return "\n".join(lines).encode("utf-8")
