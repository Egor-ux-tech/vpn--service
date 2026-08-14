"""Tests render_wireguard_config (the pure renderer moved out of WireGuardProvider — see
its module docstring) and WireGuardFormatter, which uses it for subscription-link
delivery. WireGuardProvider's own existing tests (test_wireguard_provider.py) prove the
provisioning path's output is unchanged; these tests cover the *new* no-private-key path
that only the subscription-delivery formatter exercises.
"""

import pytest

from app.models.device import Device
from app.models.enums import DeviceStatus, VPNPeerStatus, VPNServerStatus
from app.models.vpn_peer import VPNPeer
from app.models.vpn_profile import VPNProfile
from app.models.vpn_server import VPNServer
from app.services.subscription_delivery.formatters.wireguard_formatter import (
    WireGuardFormatter,
    render_wireguard_config,
)


def test_render_with_private_key_matches_existing_provisioning_shape():
    config = render_wireguard_config(
        private_key="PRIVATEKEYVALUE",
        assigned_ip="10.66.0.2/32",
        server_public_key="SERVERPUB",
        server_endpoint="vpn.example.com:51820",
        allowed_ips=["0.0.0.0/0", "::/0"],
        dns=["1.1.1.1", "1.0.0.1"],
    )
    assert "PrivateKey = PRIVATEKEYVALUE" in config
    assert "Address = 10.66.0.2/32" in config
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in config
    assert "PublicKey = SERVERPUB" in config
    assert "Endpoint = vpn.example.com:51820" in config
    assert "PersistentKeepalive = 25" in config


def test_render_without_private_key_omits_it_and_never_fabricates_one():
    config = render_wireguard_config(
        private_key=None,
        assigned_ip="10.66.0.2/32",
        server_public_key="SERVERPUB",
        server_endpoint="vpn.example.com:51820",
        allowed_ips=["0.0.0.0/0", "::/0"],
        dns=["1.1.1.1"],
    )
    assert "PrivateKey =" not in config
    assert "PRIVATEKEYVALUE" not in config
    # Still a well-formed, informative [Interface] section otherwise.
    assert "[Interface]" in config
    assert "Address = 10.66.0.2/32" in config
    assert "[Peer]" in config
    assert "PublicKey = SERVERPUB" in config


def test_render_empty_allowed_ips_falls_back_to_full_tunnel():
    config = render_wireguard_config(
        private_key="X",
        assigned_ip="10.66.0.2/32",
        server_public_key="SERVERPUB",
        server_endpoint="vpn.example.com:51820",
        allowed_ips=[],
        dns=[],
    )
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in config


@pytest.mark.asyncio
async def test_wireguard_formatter_never_includes_a_private_key():
    formatter = WireGuardFormatter()
    device = Device(id=1, user_id=1, name="Phone", status=DeviceStatus.ACTIVE)
    peer = VPNPeer(
        id=1,
        device_id=1,
        server_id=1,
        public_key="PEERPUB",
        assigned_ip="10.66.0.5/32",
        status=VPNPeerStatus.ACTIVE,
    )
    server = VPNServer(
        id=1,
        name="NL-1",
        country="NL",
        hostname="nl1.example.com",
        agent_base_url="https://nl1.example.com:8800",
        public_key="SERVERPUB",
        endpoint="nl1.example.com:51820",
        internal_network="10.66.0.0/24",
        status=VPNServerStatus.ONLINE,
    )
    profile = VPNProfile(
        device_id=1,
        allowed_ips=["1.2.3.4/32"],
        dns=["1.1.1.1"],
        version=1,
        is_current=True,
    )

    content = await formatter.render(device=device, peer=peer, server=server, profile=profile)

    assert isinstance(content, bytes)
    text = content.decode("utf-8")
    assert "PrivateKey =" not in text
    assert "Address = 10.66.0.5/32" in text
    assert "AllowedIPs = 1.2.3.4/32" in text
    assert "PublicKey = SERVERPUB" in text
    assert formatter.content_type == "text/plain; charset=utf-8"
    assert formatter.format_id == "wireguard"


@pytest.mark.asyncio
async def test_wireguard_formatter_falls_back_to_full_tunnel_with_no_profile():
    """No VPNProfile exists yet is a real, reachable state (e.g. a device provisioned the
    instant before regenerate_profile runs) — must still render something safe, not crash
    or silently narrow AllowedIPs to nothing."""
    formatter = WireGuardFormatter()
    device = Device(id=2, user_id=1, name="Laptop", status=DeviceStatus.ACTIVE)
    peer = VPNPeer(
        id=2,
        device_id=2,
        server_id=1,
        public_key="PEERPUB2",
        assigned_ip="10.66.0.6/32",
        status=VPNPeerStatus.ACTIVE,
    )
    server = VPNServer(
        id=1,
        name="NL-1",
        country="NL",
        hostname="nl1.example.com",
        agent_base_url="https://nl1.example.com:8800",
        public_key="SERVERPUB",
        endpoint="nl1.example.com:51820",
        internal_network="10.66.0.0/24",
        status=VPNServerStatus.ONLINE,
    )

    content = await formatter.render(device=device, peer=peer, server=server, profile=None)
    text = content.decode("utf-8")
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in text
