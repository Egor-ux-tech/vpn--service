from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    get_current_user,
    get_device_service,
    get_routing_service,
    get_vpn_profile_repository,
)
from app.core.errors import NotFoundError
from app.models.user import User
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.schemas.common import ORMModel
from app.services.device_service import DeviceService
from app.services.routing_service import RoutingService

router = APIRouter(prefix="/vpn", tags=["vpn"])


class VPNProfileRead(ORMModel):
    device_id: int
    mode: str
    allowed_ips: list[str]
    dns: list[str]
    version: int


@router.get("/devices/{device_id}/profile", response_model=VPNProfileRead)
async def get_device_profile(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
    profile_repo: Annotated[VPNProfileRepository, Depends(get_vpn_profile_repository)],
) -> VPNProfileRead:
    device = await device_service.get_owned(device_id, user.id)
    profile = await profile_repo.get_current_for_device(device.id)
    if profile is None:
        raise NotFoundError("No routing profile generated yet", error_code="profile_not_found")
    return VPNProfileRead.model_validate(profile)


@router.post("/devices/{device_id}/profile/refresh", response_model=VPNProfileRead)
async def refresh_device_profile(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
    routing_service: Annotated[RoutingService, Depends(get_routing_service)],
) -> VPNProfileRead:
    """Recomputes AllowedIPs from current Smart VPN rules (e.g. after the user changed
    categories/domains, or to refresh CDN IPs) and pushes it to the device's peer."""
    device = await device_service.get_owned(device_id, user.id)
    profile = await routing_service.regenerate_profile(device, user.id)
    return VPNProfileRead.model_validate(profile)
