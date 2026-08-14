import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.api.health import router as health_router
from app.api.users import router as users_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import ENABLED_VLESS_USERS, HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL
from app.state.user_store import UserStore
from app.xray.handler_client import GrpcXrayHandlerClient
from app.xray.reconciler import UserReconciler

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


async def _periodic_reconciliation_loop(reconciler: UserReconciler, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await reconciler.reconcile(trigger="periodic")
        except Exception:  # noqa: BLE001 -- one bad cycle must never kill the loop
            logger.error("periodic_reconciliation_failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store = UserStore(settings.state_db_path)
    handler_client = GrpcXrayHandlerClient(
        settings.xray_grpc_address, timeout_seconds=settings.xray_grpc_timeout_seconds
    )
    reconciler = UserReconciler(
        handler_client, store, settings.xray_inbound_tag, settings.apply_to_live_xray
    )
    app.state.reconciler = reconciler

    logger.info(
        "agent_startup",
        xray_grpc_address=settings.xray_grpc_address,
        inbound_tag=settings.xray_inbound_tag,
        apply_to_live_xray=settings.apply_to_live_xray,
    )
    await reconciler.reconcile(trigger="startup")

    task: asyncio.Task[None] | None = None
    if settings.apply_to_live_xray:
        task = asyncio.create_task(
            _periodic_reconciliation_loop(reconciler, settings.reconciliation_interval_seconds)
        )

    yield

    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    logger.info("agent_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Xray Agent", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.include_router(users_router)
    app.include_router(health_router)

    @app.middleware("http")
    async def metrics_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=path, status_code=str(response.status_code)
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, path=path).observe(duration)
        return response

    @app.get("/metrics")
    async def metrics() -> Response:
        reconciler: UserReconciler = app.state.reconciler
        enabled = await reconciler.store.list_enabled()
        ENABLED_VLESS_USERS.set(len(enabled))
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
