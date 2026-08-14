"""Proves the fix for a real bug found during the production-readiness audit: IP
allocation was a plain check-then-act (SELECT existing peers, compute the lowest free
address in Python, INSERT later) with no database-level arbiter, so two concurrent device
provisioning requests on the same server could both compute and persist the *same* IP.

The fix adds a unique constraint on (vpn_peers.server_id, vpn_peers.assigned_ip) — see the
`3073258ed68f_add_unique_constraint...` migration — and DeviceService._create_peer_with_retry
catches the resulting IntegrityError, cleans up the now-orphaned agent-side peer, and
retries with a freshly rescanned IP. These tests prove both angles: a deterministically
engineered collision, and a genuinely concurrent multi-request scenario.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import orjson
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.deps import get_vpn_provider
from app.core.security import sign_hmac
from app.db.base import Base
from app.db.session import get_db
from app.models.enums import SubscriptionStatus, VPNServerStatus
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.vpn_server import VPNServer
from app.repositories.device_repository import DeviceRepository
from app.repositories.payment_repository import PaymentRepository
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
from app.services.device_service import DeviceService
from app.services.routing.dns_resolver import DomainResolver
from app.services.routing.engine import RoutingEngine
from app.services.routing_service import RoutingService
from app.services.subscription_link_service import SubscriptionLinkService
from app.services.vpn import ip_allocator as ip_allocator_module
from app.services.vpn_server_service import VPNServerService
from tests.fakes import FakeVPNProvider, FakeXrayAgentProvider


def _sign(payload: dict) -> str:
    settings = get_settings()
    return sign_hmac(orjson.dumps(payload), settings.payment_webhook_secret)


@pytest.fixture
def fake_vpn_provider(app):
    provider = FakeVPNProvider()
    app.dependency_overrides[get_vpn_provider] = lambda: provider
    yield provider
    del app.dependency_overrides[get_vpn_provider]


@pytest_asyncio.fixture
async def conc_db_engine(tmp_path):
    """A *file-based* SQLite engine with a real connection pool — deliberately not the
    ``:memory:`` + StaticPool engine the rest of the suite uses.

    StaticPool hands every session the same single physical connection, so "concurrent"
    sessions built on it don't get genuinely isolated transactions: a manual check (asyncio
    tasks racing an INSERT of the same unique key over StaticPool vs. over a real per-task
    connection) showed StaticPool lets all writers succeed with no constraint violation ever
    raised, while separate connections to the same on-disk file correctly serialize the
    writers and surface IntegrityError on the losers, exactly as separate Postgres
    connections would in production. Only this "genuine concurrency" test needs that
    property, so it gets its own engine instead of changing the shared fixture.
    """
    db_path = tmp_path / "ip_allocation_concurrency.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def conc_db_session(conc_db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(bind=conc_db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def conc_app(conc_db_engine):
    from app.main import app as fastapi_app

    session_factory = async_sessionmaker(bind=conc_db_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    provider = FakeVPNProvider()
    fastapi_app.dependency_overrides[get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_vpn_provider] = lambda: provider
    fastapi_app.state.limiter.reset()
    yield fastapi_app, provider
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def conc_client(conc_app) -> AsyncGenerator[AsyncClient, None]:
    fastapi_app, _provider = conc_app
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def conc_plan(conc_db_session: AsyncSession) -> Plan:
    plan = Plan(
        name="Premium",
        slug="premium",
        price="199.00",
        currency="RUB",
        duration_days=30,
        max_devices=5,
        active=True,
    )
    conc_db_session.add(plan)
    await conc_db_session.commit()
    await conc_db_session.refresh(plan)
    return plan


async def _make_online_server(db_session, *, internal_network: str = "10.90.0.0/28") -> VPNServer:
    server = VPNServer(
        name="race-test",
        country="NL",
        hostname="race.example.com",
        agent_base_url="http://localhost:9999",
        public_key="RACEPUB",
        endpoint="race.example.com:51820",
        internal_network=internal_network,
        status=VPNServerStatus.ONLINE,
        capacity=100,
    )
    db_session.add(server)
    await db_session.flush()
    await db_session.refresh(server)
    return server


def _build_device_service(db_session, provider: FakeVPNProvider) -> DeviceService:
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
        provider,
        SubscriptionLinkService(SubscriptionLinkRepository(db_session)),
        "http://localhost:8000",
        VLESSCredentialRepository(db_session),
        VLESSServerConfigRepository(db_session),
        FakeXrayAgentProvider(),
    )


async def _activate_subscription_via_webhook(
    client, internal_headers, plan, db_session, telegram_id: int
) -> dict:
    await client.post(
        "/api/v1/auth/telegram", json={"telegram_id": telegram_id}, headers=internal_headers
    )
    user_headers = {**internal_headers, "X-Telegram-User-Id": str(telegram_id)}
    create_resp = await client.post(
        "/api/v1/payments", json={"plan_id": plan.id}, headers=user_headers
    )
    payment_id = create_resp.json()["payment_id"]

    repo = PaymentRepository(db_session)
    payment = await repo.get(payment_id)
    webhook_body = {
        "external_payment_id": payment.external_payment_id,
        "status": "succeeded",
        "amount": str(plan.price),
        "currency": "RUB",
    }
    await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": _sign(webhook_body)},
    )
    return user_headers


@pytest.mark.asyncio
async def test_engineered_ip_collision_is_retried_to_a_distinct_ip(
    db_session, sample_user, sample_plan, monkeypatch
):
    """Deterministically forces two allocation attempts to compute the *same* candidate
    IP (exactly what a real race between two concurrent requests would produce), and
    proves the retry mechanism resolves it to two distinct, valid IPs — not a crash, not a
    silently duplicated IP."""
    server = await _make_online_server(db_session)
    subscription = Subscription(
        user_id=sample_user.id,
        plan_id=sample_plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        auto_renew=False,
    )
    db_session.add(subscription)
    await db_session.commit()

    provider = FakeVPNProvider()
    peer_repo = VPNPeerRepository(db_session)
    device_service = _build_device_service(db_session, provider)

    real_allocate_ip = ip_allocator_module.allocate_ip
    calls = {"n": 0}

    async def colliding_allocate_ip(*, peer_repository, server_id, network_cidr):
        calls["n"] += 1
        if calls["n"] <= 2:
            # Simulate two concurrent requests both reading the pool before either commits:
            # both compute the exact same "free" candidate.
            return "10.90.0.2/32"
        return await real_allocate_ip(
            peer_repository=peer_repository, server_id=server_id, network_cidr=network_cidr
        )

    monkeypatch.setattr("app.services.device_service.allocate_ip", colliding_allocate_ip)

    first = await device_service.provision(user=sample_user, name="Device A")
    second = await device_service.provision(user=sample_user, name="Device B")

    assert first.device.assigned_ip == "10.90.0.2/32"
    assert second.device.assigned_ip != "10.90.0.2/32", (
        "second device must NOT reuse the colliding IP"
    )
    assert second.device.assigned_ip is not None

    # The retry path must have actually engaged: 3 allocate_ip calls (1 for device A, 2 for
    # device B — the first of which collided and was retried).
    assert calls["n"] == 3

    # The orphaned agent-side peer created for the losing (colliding) attempt must have
    # been cleaned up via delete_peer — exactly one deletion, matching the one collision.
    assert len(provider.deleted) == 1

    all_peers = await peer_repo.list_for_server(server.id)
    ips = [p.assigned_ip for p in all_peers]
    assert len(ips) == len(set(ips)), f"duplicate IPs were persisted: {ips}"


@pytest.mark.asyncio
async def test_ip_allocation_conflict_error_after_exhausting_retries(
    db_session, sample_user, sample_plan, monkeypatch
):
    """If every retry keeps losing the race (pathological/sustained contention), the
    service must fail loudly with a clear, catchable error — never hang, never silently
    proceed with a bad state."""
    await _make_online_server(db_session)
    subscription = Subscription(
        user_id=sample_user.id,
        plan_id=sample_plan.id,
        status=SubscriptionStatus.ACTIVE,
        started_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        auto_renew=False,
    )
    db_session.add(subscription)
    await db_session.commit()

    provider = FakeVPNProvider()
    device_service = _build_device_service(db_session, provider)

    async def always_colliding_allocate_ip(*, peer_repository, server_id, network_cidr):
        return "10.90.0.2/32"

    monkeypatch.setattr("app.services.device_service.allocate_ip", always_colliding_allocate_ip)

    # First call succeeds and takes the IP.
    await device_service.provision(user=sample_user, name="Device A")

    from app.core.errors import ConflictError

    with pytest.raises(ConflictError) as exc_info:
        await device_service.provision(user=sample_user, name="Device B")
    assert exc_info.value.error_code == "ip_allocation_conflict"


@pytest.mark.asyncio
async def test_genuinely_concurrent_provisioning_never_assigns_duplicate_ips(
    conc_client, internal_headers, conc_plan, conc_db_session
):
    """Real concurrency, not simulated: N users provision a device on the same server at
    the same time via asyncio.gather over the actual HTTP API, each request getting its
    own DB session on its own physical connection — exactly as separate real requests
    against Postgres would (see the ``conc_db_engine`` fixture docstring for why this test
    needs its own file-based engine instead of the suite's shared ``:memory:`` + StaticPool
    one). Regardless of whether the scheduler happens to interleave them into an actual
    collision this run, the invariant that must always hold is checked directly: no two
    devices ever end up on the same IP.
    """
    server = await _make_online_server(conc_db_session, internal_network="10.91.0.0/27")
    await conc_db_session.commit()

    concurrent_user_count = 6
    telegram_ids = [7_000_000 + i for i in range(concurrent_user_count)]
    user_headers_list = []
    for telegram_id in telegram_ids:
        headers = await _activate_subscription_via_webhook(
            conc_client, internal_headers, conc_plan, conc_db_session, telegram_id
        )
        user_headers_list.append(headers)

    async def create_device(headers: dict, index: int):
        return await conc_client.post(
            "/api/v1/devices", json={"name": f"Concurrent Device {index}"}, headers=headers
        )

    responses = await asyncio.gather(
        *[create_device(headers, i) for i, headers in enumerate(user_headers_list)]
    )

    assert all(r.status_code == 201 for r in responses), [
        r.json() for r in responses if r.status_code != 201
    ]

    assigned_ips = [r.json()["device"]["assigned_ip"] for r in responses]
    assert len(assigned_ips) == concurrent_user_count
    assert len(set(assigned_ips)) == concurrent_user_count, (
        f"duplicate IPs assigned under real concurrency: {assigned_ips}"
    )

    # Cross-check directly against the database, independent of what the API reported.
    peer_repo = VPNPeerRepository(conc_db_session)
    server_peers = await peer_repo.list_for_server(server.id)
    db_ips = [p.assigned_ip for p in server_peers]
    assert len(db_ips) == len(set(db_ips)), f"duplicate IPs persisted in vpn_peers: {db_ips}"
