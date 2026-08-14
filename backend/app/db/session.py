import time
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.metrics import DB_QUERY_DURATION_SECONDS

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    echo=False,
)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(
    conn: Connection,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: ExecutionContext | None,
    executemany: bool,
) -> None:
    if context is not None:
        context._metrics_start_time = time.perf_counter()  # type: ignore[attr-defined] # noqa: SLF001


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(
    conn: Connection,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: ExecutionContext | None,
    executemany: bool,
) -> None:
    start = getattr(context, "_metrics_start_time", None)
    if start is not None:
        DB_QUERY_DURATION_SECONDS.observe(time.perf_counter() - start)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Commits on a clean request, rolls back on any exception — mirrors the
    request-scoped unit-of-work pattern: one transaction per request, never left open."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
