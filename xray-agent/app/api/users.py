from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import CreateUserRequest, RotateUserRequest, UserResponse
from app.core.auth import verify_signed_request
from app.core.logging import get_logger
from app.state.user_store import UserRecord
from app.xray.handler_client import XrayCommandError

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(verify_signed_request)])


def _to_response(record: UserRecord) -> UserResponse:
    return UserResponse(
        uuid=record.uuid,
        device_id=record.device_id,
        flow=record.flow,
        created_at=record.created_at,
        rotated_at=record.rotated_at,
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(payload: CreateUserRequest, request: Request) -> UserResponse:
    """Idempotent: calling this again with the same uuid (the normal case — the backend
    retries safely, see docs/xray-agent.md) upserts the same desired state and, if Xray
    already has a live entry for it, makes no gRPC call at all."""
    reconciler = request.app.state.reconciler
    try:
        record = await reconciler.add_user(
            uuid=payload.uuid, device_id=payload.device_id, flow=payload.flow
        )
    except XrayCommandError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    logger.info("vless_user_created", device_id=payload.device_id)
    return _to_response(record)


@router.delete("/{uuid}", status_code=204)
async def delete_user(uuid: str, request: Request) -> None:
    """Idempotent: removing an already-absent uuid is a no-op success, matching normal
    DELETE semantics — a retried backend call must never surface as an error."""
    reconciler = request.app.state.reconciler
    try:
        await reconciler.remove_user(uuid)
    except XrayCommandError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.post("/{uuid}/rotate", response_model=UserResponse)
async def rotate_user(uuid: str, payload: RotateUserRequest, request: Request) -> UserResponse:
    reconciler = request.app.state.reconciler
    try:
        record = await reconciler.rotate_user(uuid=uuid, new_uuid=payload.new_uuid)
    except XrayCommandError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    logger.info("vless_user_rotated", device_id=record.device_id)
    return _to_response(record)


@router.get("", response_model=list[UserResponse])
async def list_users(request: Request) -> list[UserResponse]:
    reconciler = request.app.state.reconciler
    records = await reconciler.list_users()
    return [_to_response(r) for r in records]
