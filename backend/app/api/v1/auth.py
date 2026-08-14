from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.config import get_settings
from app.core.deps import (
    get_admin_auth_service,
    get_user_service,
    require_internal_service,
)
from app.core.rate_limit import limiter
from app.schemas.admin import AdminBootstrapRequest, AdminLoginRequest, AdminTokenResponse
from app.schemas.user import TelegramAuthRequest, UserRead
from app.services.admin_auth_service import AdminAuthService
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/telegram", response_model=UserRead, dependencies=[Depends(require_internal_service)])
async def authenticate_telegram_user(
    payload: TelegramAuthRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserRead:
    """Called only by the trusted bot service after Telegram itself has authenticated the
    human — this endpoint upserts the corresponding `User` row."""
    user = await user_service.get_or_create_from_telegram(payload)
    return UserRead.model_validate(user)


@router.post("/admin/login", response_model=AdminTokenResponse)
@limiter.limit("10/minute")
async def admin_login(
    request: Request,  # noqa: ARG001 -- required by slowapi to key-rate-limit per client IP
    payload: AdminLoginRequest,
    admin_auth_service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> AdminTokenResponse:
    """Rate-limited tighter than the API default: admin login is a credential-stuffing /
    brute-force target."""
    admin = await admin_auth_service.authenticate(payload.email, payload.password)
    return admin_auth_service.issue_tokens(admin)


@router.post("/admin/bootstrap", response_model=AdminTokenResponse, status_code=201)
@limiter.limit("5/hour")
async def bootstrap_first_admin(
    request: Request,  # noqa: ARG001 -- required by slowapi to key-rate-limit per client IP
    payload: AdminBootstrapRequest,
    admin_auth_service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
) -> AdminTokenResponse:
    """Creates the very first admin account for environments with no shell/CLI access to
    run the seed script (see backend/app/scripts/create_admin.py for the CLI alternative).
    Gated by ADMIN_SECRET *and* only ever succeeds once — see
    AdminAuthService.bootstrap_first_admin for why a leaked secret alone isn't enough."""
    settings = get_settings()
    admin = await admin_auth_service.bootstrap_first_admin(
        email=payload.email,
        password=payload.password,
        provided_secret=payload.secret,
        expected_secret=settings.admin_secret,
    )
    return admin_auth_service.issue_tokens(admin)
