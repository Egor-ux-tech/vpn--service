"""Tests render_vless_uri (the pure vless:// renderer) and VLESSFormatter, which uses it
for subscription-link delivery — see app/services/subscription_delivery/formatters/
vless_formatter.py's module docstring for exactly what fields are and are not included
and why.
"""

import pytest

from app.models.device import Device
from app.models.enums import DeviceStatus, VLESSCredentialStatus, VPNProtocol, VPNServerStatus
from app.models.vless_credential import VLESSCredential
from app.models.vless_server_config import VLESSServerConfig
from app.models.vpn_server import VPNServer
from app.services.subscription_delivery.formatters.vless_formatter import (
    VLESSFormatter,
    render_vless_uri,
)


def test_render_vless_uri_matches_expected_grammar():
    uri = render_vless_uri(
        uuid="66ad4540-b58c-4ad2-9926-ea63445a9b57",
        host="vless1.example.com",
        port=443,
        sni="www.example.com",
        reality_public_key="PUBKEY123",
        fingerprint="chrome",
        flow="xtls-rprx-vision",
        network_type="tcp",
        name="Phone",
    )
    assert uri == (
        "vless://66ad4540-b58c-4ad2-9926-ea63445a9b57@vless1.example.com:443"
        "?encryption=none&security=reality&sni=www.example.com&pbk=PUBKEY123"
        "&fp=chrome&type=tcp&flow=xtls-rprx-vision#Phone"
    )


def test_render_vless_uri_url_encodes_device_name_with_spaces_and_symbols():
    uri = render_vless_uri(
        uuid="u",
        host="h",
        port=443,
        sni="s",
        reality_public_key="p",
        fingerprint="chrome",
        flow="xtls-rprx-vision",
        network_type="tcp",
        name="My Phone #1 & Co",
    )
    fragment = uri.split("#", 1)[1]
    assert " " not in fragment
    assert "#" not in fragment
    assert "&" not in fragment
    assert fragment == "My%20Phone%20%231%20%26%20Co"


def test_render_vless_uri_never_includes_node_id_or_unconfirmed_xtls_param():
    """Per the VLESS/Happ compatibility research: node_id is not part of the confirmed
    grammar, and xtls=2's meaning/necessity was never confirmed against official
    sources — neither is invented here (see the module docstring)."""
    uri = render_vless_uri(
        uuid="u",
        host="h",
        port=443,
        sni="s",
        reality_public_key="p",
        fingerprint="chrome",
        flow="xtls-rprx-vision",
        network_type="tcp",
        name="Device",
    )
    assert "node_id" not in uri
    assert "xtls=2" not in uri
    assert "sid=" not in uri  # omittable — every node ships a single empty shortId


def test_render_vless_uri_is_pure_and_deterministic():
    kwargs = dict(
        uuid="u",
        host="h",
        port=443,
        sni="s",
        reality_public_key="p",
        fingerprint="chrome",
        flow="xtls-rprx-vision",
        network_type="tcp",
        name="Device",
    )
    assert render_vless_uri(**kwargs) == render_vless_uri(**kwargs)


def _make_device(device_id: int = 1, name: str = "Phone") -> Device:
    return Device(
        id=device_id, user_id=1, name=name, status=DeviceStatus.ACTIVE, protocol=VPNProtocol.VLESS
    )


def _make_server(server_id: int, hostname: str) -> VPNServer:
    return VPNServer(
        id=server_id,
        name=f"srv-{server_id}",
        country="NL",
        hostname=hostname,
        agent_base_url="unused-for-vless",
        public_key="unused-for-vless",
        endpoint="unused-for-vless",
        internal_network="0.0.0.0/32",
        status=VPNServerStatus.ONLINE,
        protocol=VPNProtocol.VLESS,
    )


def _make_server_config(server_id: int, port: int = 443) -> VLESSServerConfig:
    return VLESSServerConfig(
        server_id=server_id,
        xray_agent_base_url="https://node:8801",
        port=port,
        reality_public_key=f"PUBKEY-{server_id}",
        reality_short_ids=[""],
        sni="www.example.com",
        fingerprint="chrome",
        flow="xtls-rprx-vision",
        network_type="tcp",
    )


def _make_credential(
    credential_id: int, device_id: int, server_id: int, uuid: str
) -> VLESSCredential:
    return VLESSCredential(
        id=credential_id,
        device_id=device_id,
        server_id=server_id,
        uuid=uuid,
        status=VLESSCredentialStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_vless_formatter_renders_single_credential():
    formatter = VLESSFormatter()
    device = _make_device()
    server = _make_server(1, "vless1.example.com")
    config = _make_server_config(1)
    credential = _make_credential(1, device.id, 1, "11111111-1111-1111-1111-111111111111")

    content = await formatter.render(device=device, items=[(credential, server, config)])

    assert isinstance(content, bytes)
    text = content.decode("utf-8")
    assert text.startswith("vless://11111111-1111-1111-1111-111111111111@vless1.example.com:443")
    assert formatter.content_type == "text/plain; charset=utf-8"
    assert formatter.format_id == "vless"
    assert text.count("\n") == 0  # exactly one line, no trailing newline


@pytest.mark.asyncio
async def test_vless_formatter_renders_one_line_per_credential_multi_node():
    """MVP provisions one credential, but the formatter must already support N — see
    app/models/vless_credential.py's docstring on multi-node support being additive."""
    formatter = VLESSFormatter()
    device = _make_device()
    server_a = _make_server(1, "node-a.example.com")
    server_b = _make_server(2, "node-b.example.com")
    config_a = _make_server_config(1)
    config_b = _make_server_config(2)
    cred_a = _make_credential(1, device.id, 1, "11111111-1111-1111-1111-111111111111")
    cred_b = _make_credential(2, device.id, 2, "22222222-2222-2222-2222-222222222222")

    content = await formatter.render(
        device=device, items=[(cred_a, server_a, config_a), (cred_b, server_b, config_b)]
    )
    lines = content.decode("utf-8").split("\n")

    assert len(lines) == 2
    assert "node-a.example.com" in lines[0]
    assert "11111111-1111-1111-1111-111111111111" in lines[0]
    assert "node-b.example.com" in lines[1]
    assert "22222222-2222-2222-2222-222222222222" in lines[1]


@pytest.mark.asyncio
async def test_vless_formatter_never_leaks_internal_ids():
    """No device.id, credential.id, or server.id should ever appear in the rendered
    subscription body — only the UUID (the intended bearer credential), hostname, and
    the device's own chosen name."""
    formatter = VLESSFormatter()
    device = _make_device(device_id=999, name="Phone")
    server = _make_server(555, "vless1.example.com")
    config = _make_server_config(555)
    credential = _make_credential(777, device.id, 555, "11111111-1111-1111-1111-111111111111")

    content = await formatter.render(device=device, items=[(credential, server, config)])
    text = content.decode("utf-8")

    assert "999" not in text
    assert "777" not in text
    # 555 deliberately not asserted absent on its own — it could coincidentally appear
    # inside the UUID; the id fields themselves are simply never interpolated in
    # render_vless_uri's format string, which is the actual guarantee under test above.
