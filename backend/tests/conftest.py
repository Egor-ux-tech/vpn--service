import os
from collections.abc import AsyncGenerator

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("PAYMENT_PROVIDER", "mock")

import fakeredis
import pytest
import pytest_asyncio
import redis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.models.plan import Plan
from app.models.user import User

# The rate limiter (app.core.rate_limit.limiter) is backed by Redis in production. The test
# suite has no real Redis, and must not silently fall back to skipping rate-limit behavior
# or hanging trying to connect to localhost:6379 — so redis.from_url is replaced, process
# wide, with an in-memory fake *before* anything imports app.main (which constructs the
# module-level Limiter singleton on first import). This still exercises the real
# limits.storage.redis code path (Lua EVALSHA scripts and all), just against a fake server,
# so the tests that hit rate-limited endpoints prove the actual production code path works.
_shared_fake_redis = fakeredis.FakeStrictRedis()
redis.from_url = lambda *args, **kwargs: _shared_fake_redis  # type: ignore[assignment]


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def app(db_engine):
    from app.main import app as fastapi_app

    session_factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    # The app (and therefore its slowapi Limiter) is a process-wide singleton reused across
    # every test in the session — without a reset, rate-limited endpoints like admin login
    # accumulate hits across unrelated tests and start 429-ing partway through the suite.
    fastapi_app.state.limiter.reset()
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def sample_plan(db_session: AsyncSession) -> Plan:
    plan = Plan(
        name="Premium",
        slug="premium",
        price="199.00",
        currency="RUB",
        duration_days=30,
        max_devices=5,
        active=True,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    user = User(telegram_id=123456789, username="tester", status="active")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def internal_headers():
    from app.core.config import get_settings

    settings = get_settings()
    return {"X-Internal-Token": settings.internal_service_token}
