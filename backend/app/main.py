from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

from app.api.sub import router as subscription_delivery_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import (
    ACTIVE_DEVICES,
    ACTIVE_SUBSCRIPTIONS,
    ACTIVE_USERS,
    ONLINE_PEERS,
    ONLINE_SERVERS,
)
from app.core.middleware import (
    MetricsMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import limiter
from app.db.session import AsyncSessionLocal
from app.services.stats_service import compute_dashboard_counts

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("app_startup", environment=settings.environment)
    yield
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="VPN Service API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MetricsMiddleware)
    # Applies `default_limits` (RATE_LIMIT_DEFAULT, e.g. 100/minute per client IP) to every
    # route. Individual endpoints can still opt into a stricter limit via `@limiter.limit(...)`
    # (see auth.py's admin login route for a brute-force-focused example).
    app.add_middleware(SlowAPIMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router)
    app.include_router(subscription_delivery_router)

    @app.get("/health", tags=["meta"])
    async def health() -> JSONResponse:
        """Liveness probe — process is up. Does not touch the database."""
        return JSONResponse({"status": "ok"})

    @app.get("/ready", tags=["meta"])
    async def ready() -> JSONResponse:
        """Readiness probe — confirms the database is reachable."""
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            logger.error("readiness_check_failed", error=str(exc))
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/metrics", tags=["meta"])
    async def metrics() -> Response:
        """Prometheus scrape endpoint. Gauges reflecting current DB state are refreshed
        synchronously on each scrape rather than kept continuously up to date in the
        background — simple and accurate at typical scrape intervals (15-30s)."""
        async with AsyncSessionLocal() as session:
            counts = await compute_dashboard_counts(session)
        ACTIVE_USERS.set(counts.total_users)
        ACTIVE_SUBSCRIPTIONS.set(counts.active_subscriptions)
        ACTIVE_DEVICES.set(counts.active_devices)
        ONLINE_SERVERS.set(counts.online_servers)
        ONLINE_PEERS.set(counts.online_peers)
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
