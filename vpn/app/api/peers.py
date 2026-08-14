from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.schemas import (
    AllowedIPsUpdateRequest,
    CreatePeerRequest,
    CreatePeerResponse,
    PeerStatusResponse,
)
from app.core.auth import verify_signed_request
from app.core.logging import get_logger
from app.wireguard.keygen import generate_keypair

logger = get_logger(__name__)

router = APIRouter(prefix="/peers", tags=["peers"], dependencies=[Depends(verify_signed_request)])

# WireGuard public keys are base64 and may contain '/', '+', '=' — a raw path segment like
# `/peers/{public_key}` breaks because ASGI servers decode percent-escaped slashes into the
# `path` scope key before routing, so an encoded '/' is indistinguishable from a real path
# separator. Query strings don't have this ambiguity, so every peer-scoped endpoint below
# takes `public_key` as a query parameter instead.
PublicKeyParam = Query(..., description="Base64 WireGuard public key identifying the peer")


@router.post("", response_model=CreatePeerResponse, status_code=201)
async def create_peer(payload: CreatePeerRequest, request: Request) -> CreatePeerResponse:
    reconciler = request.app.state.reconciler
    keypair = generate_keypair()

    await reconciler.add_peer(
        public_key=keypair.public_key, device_id=payload.device_id, assigned_ip=payload.assigned_ip
    )

    logger.info("peer_created", device_id=payload.device_id, public_key=keypair.public_key)
    # The private key is returned exactly once, in this response, and is never stored or
    # logged by the agent from this point on.
    return CreatePeerResponse(
        public_key=keypair.public_key,
        private_key=keypair.private_key,
        assigned_ip=payload.assigned_ip,
    )


@router.delete("", status_code=204)
async def delete_peer(request: Request, public_key: str = PublicKeyParam) -> None:
    reconciler = request.app.state.reconciler
    await reconciler.remove_peer(public_key)
    logger.info("peer_deleted", public_key=public_key)


@router.post("/disable", status_code=204)
async def disable_peer(request: Request, public_key: str = PublicKeyParam) -> None:
    reconciler = request.app.state.reconciler
    record = await reconciler.store.get(public_key)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Peer not found")
    await reconciler.disable_peer(public_key)
    logger.info("peer_disabled", public_key=public_key)


@router.post("/enable", status_code=204)
async def enable_peer(request: Request, public_key: str = PublicKeyParam) -> None:
    reconciler = request.app.state.reconciler
    record = await reconciler.store.get(public_key)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Peer not found")
    await reconciler.enable_peer(public_key)
    logger.info("peer_enabled", public_key=public_key)


@router.post("/allowed-ips", status_code=204)
async def set_allowed_ips(
    payload: AllowedIPsUpdateRequest, request: Request, public_key: str = PublicKeyParam
) -> None:
    reconciler = request.app.state.reconciler
    record = await reconciler.store.get(public_key)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Peer not found")
    await reconciler.set_allowed_ips(public_key, payload.allowed_ips)


@router.get("/status", response_model=PeerStatusResponse)
async def get_peer_status(request: Request, public_key: str = PublicKeyParam) -> PeerStatusResponse:
    reconciler = request.app.state.reconciler
    record = await reconciler.store.get(public_key)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Peer not found")

    if not record.enabled:
        return PeerStatusResponse(
            public_key=public_key, status="disabled", last_handshake_at=None, rx_bytes=0, tx_bytes=0
        )

    stats = await reconciler.get_peer_stats(public_key)
    return PeerStatusResponse(
        public_key=public_key,
        status="active",
        last_handshake_at=stats.latest_handshake if stats else None,
        rx_bytes=stats.rx_bytes if stats else 0,
        tx_bytes=stats.tx_bytes if stats else 0,
    )
