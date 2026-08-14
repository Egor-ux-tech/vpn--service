"""Regression test for a real bug: the production `get_db()` dependency originally never
called `session.commit()`, so nothing written through it ever actually persisted — every
other test in this suite uses a *different*, test-only override of `get_db` (see
tests/conftest.py's `app` fixture) that already committed correctly, so it could never have
caught this. This test exercises the real, unmodified `app.db.session.get_db` end to end
against a throwaway SQLite file, independent of the FastAPI dependency-override machinery.
"""

import contextlib
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base


@pytest_asyncio.fixture
async def file_db_url():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield url
    os.remove(path)


@pytest.mark.asyncio
async def test_get_db_commits_on_success(file_db_url, monkeypatch):
    import app.db.session as db_session_module

    engine = create_async_engine(file_db_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", session_factory)

    from app.models.plan import Plan

    # First get_db() context: write a row and let the generator run to completion, exactly
    # as FastAPI does for a successful request.
    gen = db_session_module.get_db()
    session = await gen.__anext__()
    session.add(
        Plan(name="Persisted", slug="persisted", price="1.00", duration_days=30, max_devices=1)
    )
    with contextlib.suppress(StopAsyncIteration):
        await gen.__anext__()  # expected: generator completes after the implicit commit

    # Second, completely independent get_db() context/session: if the first one actually
    # committed, this fresh session must see the row.
    gen2 = db_session_module.get_db()
    session2 = await gen2.__anext__()
    from sqlalchemy import select

    result = await session2.execute(select(Plan).where(Plan.slug == "persisted"))
    assert result.scalar_one_or_none() is not None, (
        "row written via get_db() was not visible from a separate session — "
        "get_db() is not committing"
    )
    await gen2.aclose()

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception(file_db_url, monkeypatch):
    import app.db.session as db_session_module

    engine = create_async_engine(file_db_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(db_session_module, "AsyncSessionLocal", session_factory)

    from app.models.plan import Plan

    gen = db_session_module.get_db()
    session = await gen.__anext__()
    session.add(
        Plan(name="RolledBack", slug="rolled-back", price="1.00", duration_days=30, max_devices=1)
    )
    with pytest.raises(RuntimeError, match="simulated request failure"):
        await gen.athrow(RuntimeError("simulated request failure"))

    gen2 = db_session_module.get_db()
    session2 = await gen2.__anext__()
    from sqlalchemy import select

    result = await session2.execute(select(Plan).where(Plan.slug == "rolled-back"))
    assert result.scalar_one_or_none() is None, "row should have been rolled back, but persisted"
    await gen2.aclose()

    await engine.dispose()
