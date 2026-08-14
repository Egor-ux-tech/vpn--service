import ipaddress

import pytest

from app.models.enums import RouteType
from app.services.routing.engine import RoutingEngine
from tests.fakes import FakeDomainResolver


def _covers(allowed_ips: list[str], ip: str) -> bool:
    """Adjacent /32s are legitimately collapsed into wider CIDRs (e.g. two consecutive
    addresses become a /31) — assert coverage via containment, not exact-string match."""
    addr = ipaddress.ip_address(ip)
    return any(addr in ipaddress.ip_network(cidr) for cidr in allowed_ips)


@pytest.mark.asyncio
async def test_build_allowed_ips_only_includes_vpn_routed_domains():
    resolver = FakeDomainResolver(
        {
            "youtube.com": ["1.2.3.4", "1.2.3.9"],
            "sber.ru": ["9.9.9.9"],
        }
    )
    engine = RoutingEngine(resolver)

    rules = [("youtube.com", RouteType.VPN), ("sber.ru", RouteType.DIRECT)]
    allowed_ips = await engine.build_allowed_ips(rules)

    assert _covers(allowed_ips, "1.2.3.4")
    assert _covers(allowed_ips, "1.2.3.9")
    assert not _covers(allowed_ips, "9.9.9.9")


@pytest.mark.asyncio
async def test_build_allowed_ips_handles_multiple_records_per_domain_cdn_style():
    cdn_ips = [f"10.0.0.{i}" for i in range(1, 6)]
    resolver = FakeDomainResolver({"cdn.example.com": cdn_ips})
    engine = RoutingEngine(resolver)

    allowed_ips = await engine.build_allowed_ips([("cdn.example.com", RouteType.VPN)])

    assert all(_covers(allowed_ips, ip) for ip in cdn_ips)


@pytest.mark.asyncio
async def test_build_allowed_ips_supports_ipv6():
    resolver = FakeDomainResolver({"example.com": ["2001:db8::1"]})
    engine = RoutingEngine(resolver)

    allowed_ips = await engine.build_allowed_ips([("example.com", RouteType.VPN)])

    assert allowed_ips == ["2001:db8::1/128"]


@pytest.mark.asyncio
async def test_build_allowed_ips_empty_when_no_domains_are_vpn_routed():
    resolver = FakeDomainResolver({"sber.ru": ["9.9.9.9"]})
    engine = RoutingEngine(resolver)

    allowed_ips = await engine.build_allowed_ips([("sber.ru", RouteType.DIRECT)])

    assert allowed_ips == []


def test_full_vpn_allowed_ips_routes_everything():
    assert RoutingEngine.full_vpn_allowed_ips() == ["0.0.0.0/0", "::/0"]
