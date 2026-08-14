"""Transaction-behavior tests against real PostgreSQL: plain commit/rollback, the
SAVEPOINT-based retry mechanism DeviceService._create_peer_with_retry depends on for the
IP-allocation race fix (see tests/integration/test_ip_allocation_concurrency.py for the
SQLite-side proof), and a direct exercise of that exact production code path against
Postgres.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.enums import SubscriptionStatus, VPNServerStatus
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.vpn_server import VPNServer
from app.repositories.device_repository import DeviceRepository
from app.repositories.routing_repository import (
    RoutingCategoryRepository,
    RoutingRuleRepository,
    UserCategoryPreferenceRepository,
    UserCustomDomainRepository,
    UserRoutingProfileRepository,
)
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.repositories.vpn_server_repository import VPNServerRepository
from app.services.device_service import DeviceService
from app.services.routing.dns_resolver import DomainResolver
from app.services.routing.engine import RoutingEngine
from app.services.routing_service import RoutingService
from app.services.vpn import ip_allocator as ip_allocator_module
from app.services.vpn_server_service import VPNServerService
from tests.fakes import FakeVPNProvider


async def test_commit_persists_and_is_visible_on_a_separate_connection(
    pg_session: AsyncSession, migrated_postgres: str
) -> None:
    user = User(telegram_id=990001, username="pg-commit-test", status="active")
    pg_session.add(user)
    await pg_session.commit()  # a SAVEPOINT release, per join_transaction_mode — see conftest

    engine = create_async_engine(migrated_postgres)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT username FROM users WHERE telegram_id = :tid"), {"tid": 990001}
        )
        row = result.first()
    await engine.dispose()

    assert row is not None, (
        "insert+commit inside pg_session's savepoint must be visible to a fresh "
        "connection — if it weren't, session.commit() wouldn't behave like a real commit "
        "for application code under test"
    )
    assert row[0] == "pg-commit-test"


async def test_rollback_discards_uncommitted_changes(pg_session: AsyncSession) -> None:
    user = User(telegram_id=990002, username="pg-rollback-test", status="active")
    pg_session.add(user)
    await pg_session.flush()
    await pg_session.rollback()

    result = await pg_session.execute(select(User).where(User.telegram_id == 990002))
    assert result.first() is None


async def test_nested_savepoint_rollback_does_not_abort_outer_transaction(
    pg_session: AsyncSession,
) -> None:
    """Exactly the pattern DeviceService._create_peer_with_retry relies on: a duplicate
    key inside `session.begin_nested()` must only unwind that inner SAVEPOINT, leaving
    everything committed/pending outside it untouched — proven here against real Postgres,
    not SQLite."""
    outer_user = User(telegram_id=990003, username="outer", status="active")
    pg_session.add(outer_user)
    await pg_session.flush()

    duplicate = User(telegram_id=990003, username="dup", status="active")  # same telegram_id
    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            pg_session.add(duplicate)
            await pg_session.flush()

    # The outer, non-nested work must still be intact and committable.
    await pg_session.commit()
    result = await pg_session.execute(select(User).where(User.telegram_id == 990003))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].username == "outer"


def _build_device_service(session: AsyncSession, provider: FakeVPNProvider) -> DeviceService:
    routing_service = RoutingService(
        RoutingCategoryRepository(session),
        RoutingRuleRepository(session),
        UserRoutingProfileRepository(session),
        UserCategoryPreferenceRepository(session),
        UserCustomDomainRepository(session),
        VPNProfileRepository(session),
        RoutingEngine(DomainResolver()),
    )
    return DeviceService(
        DeviceRepository(session),
        VPNPeerRepository(session),
        SubscriptionRepository(session),
        VPNServerService(VPNServerRepository(session)),
        routing_service,
        provider,
    )


async def test_ip_allocation_retry_against_real_postgres(
    pg_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact production code path from the IP-allocation race fix
    (DeviceService.provision -> _create_peer_with_retry), run unmodified against real
    Postgres: two allocation attempts are forced to compute the same candidate IP, and the
    unique constraint + IntegrityError-catch-and-retry must resolve it to two distinct
    IPs — not a crash, not a silently duplicated IP, not a Postgres-specific transaction
    abort that SQLite wouldn't have surfaced.
    """
    user = User(telegram_id=990004, username="pg-ip-retry", status="active")
    pg_session.add(user)
    await pg_session.flush()

    plan = Plan(
        name="PG Test Plan",
        slug=f"pg-test-plan-{990004}",
        price="199.00",
        currency="RUB",
        duration_days=30,
        max_devices=5,
        active=True,
    )
    pg_session.add(plan)
    await pg_session.flush()

    server = VPNServer(
        name="pg-race-test",
        country="NL",
        hostname="pg-race.example.com",
        agent_base_url="http://localhost:9999",
        public_key="PGRACEPUB",
        endpoint="pg-race.example.com:51820",
        internal_network="10.92.0.0/28",
        status=VPNServerStatus.ONLINE,
        capacity=100,
    )
    pg_session.add(server)
    await pg_session.flush()

    subscription = Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        auto_renew=False,
    )
    pg_session.add(subscription)
    await pg_session.commit()

    provider = FakeVPNProvider()
    device_service = _build_device_service(pg_session, provider)

    real_allocate_ip = ip_allocator_module.allocate_ip
    calls = {"n": 0}

    async def colliding_allocate_ip(*, peer_repository, server_id, network_cidr):
        calls["n"] += 1
        if calls["n"] <= 2:
            return "10.92.0.2/32"
        return await real_allocate_ip(
            peer_repository=peer_repository, server_id=server_id, network_cidr=network_cidr
        )

    monkeypatch.setattr("app.services.device_service.allocate_ip", colliding_allocate_ip)

    first = await device_service.provision(user=user, name="PG Device A")
    second = await device_service.provision(user=user, name="PG Device B")

    assert first.device.assigned_ip == "10.92.0.2/32"
    assert second.device.assigned_ip != "10.92.0.2/32"
    assert second.device.assigned_ip is not None
    assert calls["n"] == 3
    assert len(provider.deleted) == 1

    peer_repo = VPNPeerRepository(pg_session)
    all_peers = await peer_repo.list_for_server(server.id)
    ips = [p.assigned_ip for p in all_peers]
    assert len(ips) == len(set(ips)), f"duplicate IPs persisted on real Postgres: {ips}"
