from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import DeviceStatus, SubscriptionStatus, VPNServerStatus
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
from tests.fakes import FakeVPNProvider, FakeXrayAgentProvider


class _RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def notify(self, *, telegram_id: int, message: str) -> None:
        self.sent.append((telegram_id, message))


async def _provision_active_subscription_with_device(db_session, sample_user, sample_plan):
    from app.models.subscription import Subscription
    from app.models.vpn_server import VPNServer

    server = VPNServer(
        name="expiry-test",
        country="NL",
        hostname="localhost",
        agent_base_url="http://localhost:9999",
        public_key="SERVERPUB",
        endpoint="localhost:51820",
        internal_network="10.66.0.0/24",
        status=VPNServerStatus.ONLINE,
        capacity=10,
    )
    db_session.add(server)
    await db_session.flush()

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
async def test_expiry_worker_expires_subscription_disables_devices_and_notifies(
    db_session, sample_user, sample_plan
):
    subscription, server = await _provision_active_subscription_with_device(
        db_session, sample_user, sample_plan
    )

    provider = FakeVPNProvider()
    device_repo = DeviceRepository(db_session)
    peer_repo = VPNPeerRepository(db_session)
    server_service = VPNServerService(VPNServerRepository(db_session))
    routing_service = RoutingService(
        RoutingCategoryRepository(db_session),
        RoutingRuleRepository(db_session),
        UserRoutingProfileRepository(db_session),
        UserCategoryPreferenceRepository(db_session),
        UserCustomDomainRepository(db_session),
        VPNProfileRepository(db_session),
        RoutingEngine(DomainResolver()),
    )
    device_service = DeviceService(
        device_repo,
        peer_repo,
        SubscriptionRepository(db_session),
        server_service,
        routing_service,
        provider,
        SubscriptionLinkService(SubscriptionLinkRepository(db_session)),
        "http://localhost:8000",
        VLESSCredentialRepository(db_session),
        VLESSServerConfigRepository(db_session),
        FakeXrayAgentProvider(),
    )

    device_result = await device_service.provision(
        user=sample_user, name="Laptop", requested_server_id=server.id
    )
    await db_session.commit()
    assert device_result.device.status == DeviceStatus.ACTIVE

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

    await db_session.refresh(subscription)
    assert subscription.status is SubscriptionStatus.EXPIRED

    devices = await device_repo.list_for_user(sample_user.id)
    assert all(d.status == DeviceStatus.DISABLED for d in devices)
    assert len(provider.disabled) == 1

    assert len(notifier.sent) == 1
    assert notifier.sent[0][0] == sample_user.telegram_id
    assert "истекла" in notifier.sent[0][1]


@pytest.mark.asyncio
async def test_expiry_worker_is_a_no_op_when_nothing_expired(db_session, sample_user, sample_plan):
    notifier = _RecordingNotifier()
    device_repo = DeviceRepository(db_session)
    server_service = VPNServerService(VPNServerRepository(db_session))
    routing_service = RoutingService(
        RoutingCategoryRepository(db_session),
        RoutingRuleRepository(db_session),
        UserRoutingProfileRepository(db_session),
        UserCategoryPreferenceRepository(db_session),
        UserCustomDomainRepository(db_session),
        VPNProfileRepository(db_session),
        RoutingEngine(DomainResolver()),
    )
    device_service = DeviceService(
        device_repo,
        VPNPeerRepository(db_session),
        SubscriptionRepository(db_session),
        server_service,
        routing_service,
        FakeVPNProvider(),
        SubscriptionLinkService(SubscriptionLinkRepository(db_session)),
        "http://localhost:8000",
        VLESSCredentialRepository(db_session),
        VLESSServerConfigRepository(db_session),
        FakeXrayAgentProvider(),
    )
    worker = SubscriptionExpiryWorker(
        subscription_service=SubscriptionService(SubscriptionRepository(db_session)),
        device_service=device_service,
        audit_service=AuditService(AuditLogRepository(db_session)),
        notifier=notifier,
    )

    summary = await worker.run_once()

    assert summary.count == 0
    assert notifier.sent == []
