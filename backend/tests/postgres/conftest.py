"""Fixtures for tests that run against a *real* PostgreSQL instance, not SQLite.

The rest of the suite (tests/conftest.py) runs entirely on aiosqlite for speed, which is
fine for exercising application logic but cannot validate anything dialect-specific:
whether a migration written/tested against SQLite (see the batch_alter_table comment on
3073258ed68f_add_unique_constraint_on_vpn_peers_...) actually produces the intended schema
on Postgres, whether SAVEPOINT-based retry (DeviceService._create_peer_with_retry) behaves
the same under Postgres's real locking, etc. Production only ever runs Postgres — see
docker-compose.yml — so that gap is exactly what this package closes.

These tests need a running Postgres reachable at POSTGRES_TEST_DATABASE_URL and are skipped
entirely (not faked, not run against SQLite instead) when that isn't set — which is the
normal case for a quick local `pytest` run. To run them:

    docker compose up -d postgres
    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://vpnservice:change-me@localhost:5432/vpnservice \
        python -m pytest tests/postgres -v

CI runs them on every push via a `postgres:16-alpine` service container (see
.github/workflows/backend.yml) — the same image docker-compose.yml uses in production.
"""

import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]

POSTGRES_TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")

_SKIP_REASON = (
    "POSTGRES_TEST_DATABASE_URL not set — skipping real-Postgres tests. Not a failure: "
    "these need docker compose up -d postgres locally, or run automatically in CI "
    "against a postgres service container. See this package's docstring."
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """A plain `pytestmark` here would only apply to conftest.py itself (which has no
    tests) — it does not propagate to sibling test modules in this package. This hook is
    the correct way to skip every test collected under tests/postgres/ when there's no
    Postgres to run them against."""
    if POSTGRES_TEST_DATABASE_URL is not None:
        return
    skip = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        if "tests/postgres/" in str(item.path).replace(os.sep, "/"):
            item.add_marker(skip)


def _sync_dsn(async_url: str) -> str:
    """asyncpg.connect wants a plain postgres:// DSN, not SQLAlchemy's +asyncpg driver URL."""
    return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def _reset_to_truly_empty_database(url: str) -> None:
    """Drops and recreates the public schema so migrations run against a genuinely empty
    database each time this suite runs — not "empty apart from whatever the last run or a
    developer's manual testing left behind"."""
    conn = await asyncpg.connect(_sync_dsn(url))
    try:
        await conn.execute("DROP SCHEMA public CASCADE")
        await conn.execute("CREATE SCHEMA public")
    finally:
        await conn.close()


def run_alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="package")
def postgres_url() -> str:
    assert POSTGRES_TEST_DATABASE_URL is not None  # guaranteed by pytestmark skip above
    return POSTGRES_TEST_DATABASE_URL


@pytest_asyncio.fixture(scope="package")
async def migrated_postgres(postgres_url: str) -> AsyncGenerator[str, None]:
    """Resets the test database to empty, then runs the real `alembic upgrade head`
    command (subprocess, not the Python API) — exactly what docs/deployment.md tells an
    operator to run in production. Session-scoped: the reset+migrate is real I/O against a
    real database and every test in this package wants the same fully-migrated schema, not
    a fresh one each time — individual tests isolate their own data via `pg_session`
    truncating every table at teardown, not by re-migrating.
    """
    await _reset_to_truly_empty_database(postgres_url)
    result = run_alembic("upgrade", "head", database_url=postgres_url)
    assert result.returncode == 0, (
        f"alembic upgrade head failed against an empty Postgres database:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    yield postgres_url


async def _truncate_all_tables(url: str) -> None:
    """Resets every application table to empty (but leaves the migrated schema and
    alembic_version alone) between tests.

    An earlier version of this fixture tried the fancier SQLAlchemy "join a Session into an
    external transaction" recipe (a real transaction + a Session bound to it via
    join_transaction_mode="create_savepoint", rolled back at teardown so nothing a test
    commits ever really persists) — the pattern SQLAlchemy's own docs recommend for this
    exact scenario. A smoke test against SQLite caught it silently failing to discard a
    committed row after the outer rollback, and there was no real Postgres available in
    this environment to confirm whether that was a SQLite-only quirk (SQLite/pysqlite's
    autocommit handling is a known source of exactly this kind of surprise) or a real bug
    in the fixture. Rather than ship isolation logic whose correctness nobody has verified,
    every test here uses a plain Session with real commits — identical to how
    DeviceService/repositories actually run in production — and cleans up via TRUNCATE
    instead. Less clever, directly verifiable, nothing to trust blindly.
    """
    conn = await asyncpg.connect(_sync_dsn(url))
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename != 'alembic_version'"
        )
        tables = [row["tablename"] for row in rows]
        if tables:
            quoted = ", ".join(f'"{t}"' for t in tables)
            await conn.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def pg_session(migrated_postgres: str) -> AsyncGenerator[AsyncSession, None]:
    """A plain Session against the real, migrated Postgres database — commits are real
    commits, exactly as in production. Truncates every table at teardown so the next test
    starts from an empty (but still migrated) database, regardless of what this test
    committed, raised, or left half-finished."""
    engine = create_async_engine(migrated_postgres)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
        await _truncate_all_tables(migrated_postgres)
