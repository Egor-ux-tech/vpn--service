from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, get_device_service
from app.models.user import User
from app.schemas.device import DeviceCreateRequest, DeviceProvisioningResult, DeviceRead
from app.services.device_service import DeviceService

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> list[DeviceRead]:
    devices = await service.list_for_user(user.id)
    return [DeviceRead.model_validate(d) for d in devices]


@router.post("", response_model=DeviceProvisioningResult, status_code=201)
async def create_device(
    payload: DeviceCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> DeviceProvisioningResult:
    result = await service.provision(
        user=user, name=payload.name, requested_server_id=payload.server_id
    )
    return DeviceProvisioningResult(
        device=DeviceRead.model_validate(result.device),
        config_text=result.config_text,
        qr_code_base64=result.qr_code_base64,
    )


@router.post("/{device_id}/reissue", response_model=DeviceProvisioningResult)
async def reissue_device_config(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> DeviceProvisioningResult:
    device = await service.get_owned(device_id, user.id)
    result = await service.reissue(device=device)
    return DeviceProvisioningResult(
        device=DeviceRead.model_validate(result.device),
        config_text=result.config_text,
        qr_code_base64=result.qr_code_base64,
    )


@router.post("/{device_id}/disable", response_model=DeviceRead)
async def disable_device(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> DeviceRead:
    device = await service.get_owned(device_id, user.id)
    device = await service.disable(device=device)
    return DeviceRead.model_validate(device)


@router.post("/{device_id}/enable", response_model=DeviceRead)
async def enable_device(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> DeviceRead:
    device = await service.get_owned(device_id, user.id)
    device = await service.enable(device=device)
    return DeviceRead.model_validate(device)


@router.delete("/{device_id}", response_model=DeviceRead)
async def revoke_device(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeviceService, Depends(get_device_service)],
) -> DeviceRead:
    device = await service.get_owned(device_id, user.id)
    device = await service.revoke(device=device)
    return DeviceRead.model_validate(device)
