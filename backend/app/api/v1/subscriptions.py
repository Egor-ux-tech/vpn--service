from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, get_subscription_service
from app.core.errors import PermissionDeniedError
from app.models.user import User
from app.schemas.subscription import SubscriptionRead
from app.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/me", response_model=list[SubscriptionRead])
async def list_my_subscriptions(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> list[SubscriptionRead]:
    subs = await service.list_for_user(user.id)
    return [SubscriptionRead.model_validate(s) for s in subs]


@router.get("/me/active", response_model=SubscriptionRead | None)
async def get_my_active_subscription(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> SubscriptionRead | None:
    sub = await service.get_active_for_user(user.id)
    return SubscriptionRead.model_validate(sub) if sub else None


@router.post("/{subscription_id}/cancel", response_model=SubscriptionRead)
async def cancel_subscription(
    subscription_id: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> SubscriptionRead:
    subscription = await service.get(subscription_id)
    if subscription.user_id != user.id:
        raise PermissionDeniedError("Not your subscription", error_code="not_your_subscription")
    subscription = await service.cancel(subscription)
    return SubscriptionRead.model_validate(subscription)
