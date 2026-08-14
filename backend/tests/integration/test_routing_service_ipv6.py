"""Proves RoutingService.regenerate_profile — the actual code path DeviceService calls
when provisioning/reissuing a device (see app/services/device_service.py) — carries the
IPv6 leak-prevention and dual-stack behavior documented in docs/wireguard.md's "IPv6
strategy" section, not just the static RoutingEngine helpers in isolation
(tests/unit/test_routing_engine.py already covers those).
"""

import pytest

from app.models.device import Device
from app.models.enums import DeviceStatus, RouteType, RoutingMode
from app.repositories.routing_repository import (
    RoutingCategoryRepository,
    RoutingRuleRepository,
    UserCategoryPreferenceRepository,
    UserCustomDomainRepository,
    UserRoutingProfileRepository,
)
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.schemas.routing import RoutingRuleCreate
from app.services.routing.engine import RoutingEngine
from app.services.routing_service import RoutingService
from tests.fakes import FakeDomainResolver


def _build_routing_service(db_session, resolver: FakeDomainResolver) -> RoutingService:
    return RoutingService(
        RoutingCategoryRepository(db_session),
        RoutingRuleRepository(db_session),
        UserRoutingProfileRepository(db_session),
        UserCategoryPreferenceRepository(db_session),
        UserCustomDomainRepository(db_session),
        VPNProfileRepository(db_session),
        RoutingEngine(resolver),
    )


async def _make_device(db_session, sample_user) -> Device:
    device = Device(user_id=sample_user.id, name="ipv6-test-device", status=DeviceStatus.ACTIVE)
    db_session.add(device)
    await db_session.flush()
    return device


@pytest.mark.asyncio
async def test_full_vpn_profile_captures_ipv6_default_route(db_session, sample_user):
    """A brand-new user defaults to full_vpn mode (see get_or_create_user_profile) — the
    resulting profile must route ::/0, not just 0.0.0.0/0, or a dual-stack client's IPv6
    traffic would silently bypass the tunnel via the OS's own default route."""
    device = await _make_device(db_session, sample_user)
    service = _build_routing_service(db_session, FakeDomainResolver({}))

    profile = await service.regenerate_profile(device, sample_user.id)

    assert profile.mode is RoutingMode.FULL_VPN
    assert "0.0.0.0/0" in profile.allowed_ips
    assert "::/0" in profile.allowed_ips


@pytest.mark.asyncio
async def test_smart_vpn_profile_includes_ipv6_addresses_for_vpn_routed_domains(
    db_session, sample_user
):
    """Smart VPN must treat a VPN-routed domain's IPv6 (AAAA) address exactly like its
    IPv4 one — not silently drop it, which would leave that specific site's IPv6 traffic
    unrouted even though the user explicitly asked for it to go through the VPN."""
    device = await _make_device(db_session, sample_user)
    resolver = FakeDomainResolver({"dual-stack.example.com": ["203.0.113.5", "2001:db8::5"]})
    service = _build_routing_service(db_session, resolver)

    await service.set_mode(sample_user.id, RoutingMode.SMART_VPN)
    category = await service.create_category("Test", "for ipv6 coverage")
    await service.add_rule(
        RoutingRuleCreate(
            category_id=category.id, domain="dual-stack.example.com", route_type=RouteType.VPN
        )
    )
    await service.set_category_preference(sample_user.id, category.id, enabled=True)
    await db_session.commit()

    profile = await service.regenerate_profile(device, sample_user.id)

    assert profile.mode is RoutingMode.SMART_VPN
    assert "203.0.113.5/32" in profile.allowed_ips
    assert "2001:db8::5/128" in profile.allowed_ips


@pytest.mark.asyncio
async def test_smart_vpn_with_no_matching_domains_falls_back_to_full_vpn_capture(
    db_session, sample_user
):
    """If Smart VPN mode resolves to zero routed addresses (no rules, or none enabled),
    regenerate_profile falls back to full-tunnel rather than provisioning a peer with an
    empty AllowedIPs — that fallback must still include ::/0, or a user in this state would
    have their IPv6 traffic leak while believing Smart VPN was protecting them."""
    device = await _make_device(db_session, sample_user)
    service = _build_routing_service(db_session, FakeDomainResolver({}))
    await service.set_mode(sample_user.id, RoutingMode.SMART_VPN)
    await db_session.commit()

    profile = await service.regenerate_profile(device, sample_user.id)

    assert "::/0" in profile.allowed_ips
    assert "0.0.0.0/0" in profile.allowed_ips
