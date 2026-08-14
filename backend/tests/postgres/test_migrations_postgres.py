"""Proves the Alembic migration chain actually works against real PostgreSQL — not just
SQLite, which is what the rest of the suite runs on and where dialect differences (e.g.
SQLite's lack of ALTER-based constraint support, worked around with batch_alter_table) can
hide a migration that would fail, or silently do the wrong thing, on the real production
database.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.postgres.conftest import run_alembic


async def test_migrations_apply_cleanly_and_create_expected_tables(migrated_postgres: str) -> None:
    """`migrated_postgres` itself already asserts `alembic upgrade head` exits 0 against an
    empty database — this additionally checks the result is the schema we expect, not just
    "some exit code 0 outcome"."""
    engine = create_async_engine(migrated_postgres)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        tables = {row[0] for row in result}
    await engine.dispose()

    expected_tables = (
        "users",
        "devices",
        "vpn_peers",
        "vpn_servers",
        "subscriptions",
        "alembic_version",
    )
    for expected in expected_tables:
        assert expected in tables, f"expected table {expected!r} missing after migration: {tables}"


async def test_alembic_version_matches_a_single_head(migrated_postgres: str) -> None:
    engine = create_async_engine(migrated_postgres)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        rows = [row[0] for row in result]
    await engine.dispose()

    assert len(rows) == 1, f"expected exactly one row in alembic_version, got {rows}"


async def test_vpn_peer_unique_constraint_exists_on_postgres(migrated_postgres: str) -> None:
    """The fix for the IP-allocation race (see DeviceService._create_peer_with_retry) is
    only as real as the constraint actually being present in the database it runs against.
    The migration was authored and hand-tested against SQLite via batch_alter_table
    (SQLite has no ALTER-based constraint support at all); this confirms that same
    migration produces a real `ALTER TABLE ... ADD CONSTRAINT` on Postgres, not something
    that silently no-ops or diverges under batch mode's Postgres code path."""
    engine = create_async_engine(migrated_postgres)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conname = 'uq_vpn_peer_server_assigned_ip'"
            )
        )
        rows = result.fetchall()
    await engine.dispose()

    assert len(rows) == 1, "uq_vpn_peer_server_assigned_ip constraint not found on Postgres"
    assert rows[0].contype == "u", f"expected a UNIQUE constraint, got contype={rows[0].contype!r}"


async def test_migration_downgrade_and_reupgrade_round_trip(migrated_postgres: str) -> None:
    """Downgrading one revision and re-upgrading must both succeed and leave the schema
    exactly as it was — proving the down_revision chain and the downgrade() implementations
    (not just upgrade()) are correct against Postgres too.

    This mutates the package-scoped `migrated_postgres` database in place (there's no
    cheaper way to test a real downgrade), so it always re-upgrades back to head in a
    finally block — leaving the schema at head for any later test in this package even if
    an assertion here fails partway through.
    """
    down = run_alembic("downgrade", "-1", database_url=migrated_postgres)
    assert down.returncode == 0, f"alembic downgrade -1 failed:\n{down.stdout}\n{down.stderr}"

    try:
        engine = create_async_engine(migrated_postgres)
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conname = 'uq_vpn_peer_server_assigned_ip'"
                )
            )
            assert result.fetchall() == [], (
                "constraint should be gone after downgrading past its migration"
            )
        await engine.dispose()
    finally:
        up = run_alembic("upgrade", "head", database_url=migrated_postgres)
        assert up.returncode == 0, (
            f"re-running alembic upgrade head failed:\n{up.stdout}\n{up.stderr}"
        )

    engine = create_async_engine(migrated_postgres)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conname = 'uq_vpn_peer_server_assigned_ip'"
            )
        )
        assert len(result.fetchall()) == 1, "constraint should be back after re-upgrading to head"
    await engine.dispose()
