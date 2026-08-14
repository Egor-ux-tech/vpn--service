from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    SettingsDep,
    get_current_user,
    get_device_service,
    get_subscription_link_service,
)
from app.core.errors import NotFoundError
from app.models.user import User
from app.schemas.subscription_link import SubscriptionLinkCreated, SubscriptionLinkRead
from app.services.device_service import DeviceService
from app.services.subscription_link_service import SubscriptionLinkService, build_subscription_url
from app.services.vpn.qrcode_util import generate_qr_code_base64

router = APIRouter(prefix="/devices/{device_id}/subscription-link", tags=["subscription-links"])


@router.post("", response_model=SubscriptionLinkCreated, status_code=201)
async def create_or_rotate_subscription_link(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    settings: SettingsDep,
    device_service: Annotated[DeviceService, Depends(get_device_service)],
    link_service: Annotated[SubscriptionLinkService, Depends(get_subscription_link_service)],
) -> SubscriptionLinkCreated:
    """Creates a link if the device has none yet, or rotates (new token, old one dies
    immediately) if it does — this is both the bootstrap path and the user-facing
    "regenerate my link" action, since both are the same operation from the service's
    point of view. See SubscriptionLinkService.create_or_rotate."""
    device = await device_service.get_owned(device_id, user.id)
    link, token = await link_service.create_or_rotate(device)
    subscription_url = build_subscription_url(settings.subscription_base_url, token)
    return SubscriptionLinkCreated(
        link=SubscriptionLinkRead.model_validate(link),
        subscription_url=subscription_url,
        qr_code_base64=generate_qr_code_base64(subscription_url),
    )


@router.get("", response_model=SubscriptionLinkRead)
async def get_subscription_link(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
    link_service: Annotated[SubscriptionLinkService, Depends(get_subscription_link_service)],
) -> SubscriptionLinkRead:
    """Metadata only — status, prefix, timestamps. The plaintext token/URL is never
    retrievable again after creation/rotation (only its hash is stored); to get a usable
    link again, rotate via POST."""
    device = await device_service.get_owned(device_id, user.id)
    link = await link_service.get_for_device(device.id)
    if link is None:
        raise NotFoundError(
            "No subscription link exists for this device yet",
            error_code="subscription_link_not_found",
        )
    return SubscriptionLinkRead.model_validate(link)


@router.delete("", response_model=SubscriptionLinkRead)
async def revoke_subscription_link(
    device_id: int,
    user: Annotated[User, Depends(get_current_user)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
    link_service: Annotated[SubscriptionLinkService, Depends(get_subscription_link_service)],
) -> SubscriptionLinkRead:
    device = await device_service.get_owned(device_id, user.id)
    link = await link_service.get_for_device(device.id)
    if link is None:
        raise NotFoundError(
            "No subscription link exists for this device yet",
            error_code="subscription_link_not_found",
        )
    link = await link_service.revoke(link)
    return SubscriptionLinkRead.model_validate(link)
