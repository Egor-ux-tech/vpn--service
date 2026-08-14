"""Proves VLESS credentials go through the SAME expiry authority as WireGuard peers —
SubscriptionExpiryWorker → DeviceService.disable_all_for_user → DeviceService.disable —
rather than a second, independent expiry mechanism (explicitly required: reuse the
existing billing/subscription authority). See test_subscription_expiry_worker.py for the
WireGuard-side equivalent this mirrors.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import (
    DeviceStatus,
    SubscriptionStatus,
    VLESSCredentialStatus,
    VPNProtocol,
    VPNServerStatus,
)
from app.models.subscription import Subscription
from app.models.vless_server_config import VLESSServerConfig
from app.models.vpn_server import VPNServer
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.routing_repository import (
    RoutingCategoryRepository,
    RoutingRuleRepository,
    UserCategoryPreferenceRepository,
    UserCustomDomainRepository,
    UserRoutingProfileRepository,
)
from app.repositories.subscription_link_repository import SubscriptionLinkRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vless_credential_repository import VLESSCredentialRepository
from app.repositories.vless_server_config_repository import VLESSServerConfigRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.repositories.vpn_server_repository import VPNServerRepository
from app.services.audit_service import AuditService
from app.services.device_service import DeviceService
from app.services.routing.dns_resolver import DomainResolver
from app.services.routing.engine import RoutingEngine
from app.services.routing_service import RoutingService
from app.services.subscription_link_service import SubscriptionLinkService
from app.services.subscription_service import SubscriptionService
from app.services.vpn_server_service import VPNServerService
from app.workers.subscription_expiry import SubscriptionExpiryWorker
from tests.fakes import FakeXrayAgentProvider


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def notify(self, *, telegram_id: int, message: str) -> None:
        self.sent.append((telegram_id, message))


def _build_device_service(db_session, xray_agent_provider):
    routing_service = RoutingService(
        RoutingCategoryRepository(db_session),
        RoutingRuleRepository(db_session),
        UserRoutingProfileRepository(db_session),
        UserCategoryPreferenceRepository(db_session),
        UserCustomDomainRepository(db_session),
        VPNProfileRepository(db_session),
        RoutingEngine(DomainResolver()),
    )
    return DeviceService(
        DeviceRepository(db_session),
        VPNPeerRepository(db_session),
        SubscriptionRepository(db_session),
        VPNServerService(VPNServerRepository(db_session)),
        routing_service,
        None,  # WireGuard VPNProvider — unused on the VLESS path exercised here
        SubscriptionLinkService(SubscriptionLinkRepository(db_session)),
        "http://localhost:8000",
        VLESSCredentialRepository(db_session),
        VLESSServerConfigRepository(db_session),
        xray_agent_provider,
    )


async def _provision_expired_vless_subscription_with_device(db_session, sample_user, sample_plan):
    server = VPNServer(
        name="vless-expiry-test",
        country="NL",
        hostname="vless-expiry.example.com",
        agent_base_url="unused-for-vless",
        public_key="unused-for-vless",
        endpoint="unused-for-vless",
        internal_network="0.0.0.0/32",
        status=VPNServerStatus.ONLINE,
        protocol=VPNProtocol.VLESS,
    )
    db_session.add(server)
    await db_session.flush()

    config = VLESSServerConfig(
        server_id=server.id,
        xray_agent_base_url="https://vless-expiry.example.com:8801",
        port=443,
        reality_public_key="PUBKEY",
        reality_short_ids=[""],
        sni="www.example.com",
        fingerprint="chrome",
        flow="xtls-rprx-vision",
        network_type="tcp",
    )
    db_session.add(config)

    subscription = Subscription(
        user_id=sample_user.id,
        plan_id=sample_plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC) - timedelta(days=31),
        expires_at=datetime.now(UTC) - timedelta(days=1),
        auto_renew=False,
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    await db_session.refresh(server)
    return subscription, server


@pytest.mark.asyncio
async def test_expiry_worker_disables_vless_credential_and_removes_from_xray(
    db_session, sample_user, sample_plan
):
    subscription, server = await _provision_expired_vless_subscription_with_device(
        db_session, sample_user, sample_plan
    )

    xray_agent_provider = FakeXrayAgentProvider()
    device_service = _build_device_service(db_session, xray_agent_provider)
    device_result = await device_service.provision(
        user=sample_user, name="Phone", requested_server_id=server.id, protocol=VPNProtocol.VLESS
    )
    await db_session.commit()
    assert device_result.device.status == DeviceStatus.ACTIVE
    assert len(xray_agent_provider.created) == 1

    device_repo = DeviceRepository(db_session)
    cred_repo = VLESSCredentialRepository(db_session)

    notifier = _RecordingNotifier()
    worker = SubscriptionExpiryWorker(
        subscription_service=SubscriptionService(SubscriptionRepository(db_session)),
        device_service=device_service,
        audit_service=AuditService(AuditLogRepository(db_session)),
        notifier=notifier,
    )

    summary = await worker.run_once()
    await db_session.commit()

    assert summary.expired_subscription_ids == [subscription.id]

    devices = await device_repo.list_for_user(sample_user.id)
    assert all(d.status == DeviceStatus.DISABLED for d in devices)

    credentials = await cred_repo.list_for_device(device_result.device.id)
    assert credentials[0].status == VLESSCredentialStatus.DISABLED

    # The credential must actually have been removed from Xray, not just marked
    # disabled in the database — this is the assertion that would fail if
    # DeviceService.disable() still only branched on VPNPeer.
    assert len(xray_agent_provider.removed) == 1
    assert xray_agent_provider.removed[0] == credentials[0].uuid
    assert credentials[0].uuid not in xray_agent_provider.users

    assert len(notifier.sent) == 1
