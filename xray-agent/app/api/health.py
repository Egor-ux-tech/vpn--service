"""Health/readiness/status — deliberately unauthenticated (like vpn-agent's /health,
/ready, /metrics), since these expose no per-user identifiers, only aggregate counts and
liveness signals; reachability is controlled by the firewall, not by request signing."""

from fastapi import APIRouter, Request

from app.api.schemas import HealthResponse, ReadyResponse, StatusResponse
from app.core.logging import get_logger
from app.xray.handler_client import XrayCommandError
from app.xray.reconciler import UserReconciler

logger = get_logger(__name__)

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Pure liveness — the agent process can respond. Does not touch Xray."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse:
    """Readiness = the local store is reachable AND Xray's gRPC API actually answers a
    real call (see XrayHandlerClient.count_users) — an agent that's up but can't reach
    Xray is not ready to serve create/remove/rotate requests."""
    reconciler = request.app.state.reconciler
    try:
        await reconciler.store.list_enabled()
    except Exception as exc:  # noqa: BLE001
        logger.error("readiness_check_failed", error=str(exc))
        return ReadyResponse(status="unavailable", xray_reachable=False)

    xray_reachable = await _check_xray_reachable(reconciler)
    return ReadyResponse(
        status="ready" if xray_reachable else "degraded", xray_reachable=xray_reachable
    )


@router.get("/status", response_model=StatusResponse)
async def get_status(request: Request) -> StatusResponse:
    reconciler = request.app.state.reconciler
    desired = await reconciler.store.list_enabled()
    xray_reachable = await _check_xray_reachable(reconciler)
    live_count = None
    if xray_reachable:
        try:
            live_count = await reconciler.count_live_users()
        except XrayCommandError:
            live_count = None
    return StatusResponse(
        status="ready" if xray_reachable else "degraded",
        xray_reachable=xray_reachable,
        active_user_count=len(desired),
        live_user_count=live_count,
        last_reconciliation_at=reconciler.last_reconciliation_at,
    )


async def _check_xray_reachable(reconciler: UserReconciler) -> bool:
    if not reconciler.apply_to_live:  # dev/test mode never has a real Xray to reach
        return True
    try:
        await reconciler.count_live_users()
    except XrayCommandError:
        return False
    return True
