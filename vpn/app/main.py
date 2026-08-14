import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import JSONResponse, Response

from app.api.peers import router as peers_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import ENABLED_PEERS, HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL
from app.state.peer_store import PeerStore
from app.wireguard.interface import WireGuardInterface
from app.wireguard.reconciler import PeerReconciler

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store = PeerStore(settings.state_db_path)
    interface = WireGuardInterface(settings.wg_interface)
    reconciler = PeerReconciler(interface, store, settings.apply_to_live_interface)
    app.state.reconciler = reconciler

    logger.info(
        "agent_startup",
        interface=settings.wg_interface,
        apply_to_live_interface=settings.apply_to_live_interface,
    )
    await reconciler.reconcile_on_startup()
    yield
    logger.info("agent_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="VPN Agent", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.include_router(peers_router)

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

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/ready")
    async def ready() -> JSONResponse:
        store: PeerStore = app.state.reconciler.store
        try:
            await store.list_enabled()
        except Exception as exc:  # noqa: BLE001
            logger.error("readiness_check_failed", error=str(exc))
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/metrics")
    async def metrics() -> Response:
        store: PeerStore = app.state.reconciler.store
        enabled = await store.list_enabled()
        ENABLED_PEERS.set(len(enabled))
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
