from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    get_audit_service,
    get_current_admin,
    get_current_user,
    get_user_repository,
    require_admin_role,
)
from app.core.errors import NotFoundError
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.common import Pagination
from app.schemas.user import UserRead, UserUpdateStatus
from app.services.audit_service import AuditService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_my_profile(user: Annotated[User, Depends(get_current_user)]) -> UserRead:
    return UserRead.model_validate(user)


@router.get(
    "",
    response_model=list[UserRead],
    dependencies=[
        Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT, AdminRole.VIEWER))
    ],
)
async def list_users(
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    pagination: Annotated[Pagination, Depends()],
) -> list[UserRead]:
    users = await repo.list(offset=pagination.offset, limit=pagination.limit)
    return [UserRead.model_validate(u) for u in users]


@router.get(
    "/{user_id}",
    response_model=UserRead,
    dependencies=[
        Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT, AdminRole.VIEWER))
    ],
)
async def get_user(
    user_id: int, repo: Annotated[UserRepository, Depends(get_user_repository)]
) -> UserRead:
    user = await repo.get(user_id)
    if user is None:
        raise NotFoundError("User not found", error_code="user_not_found")
    return UserRead.model_validate(user)


@router.patch(
    "/{user_id}/status",
    response_model=UserRead,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT))],
)
async def update_user_status(
    user_id: int,
    payload: UserUpdateStatus,
    repo: Annotated[UserRepository, Depends(get_user_repository)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> UserRead:
    user = await repo.get(user_id)
    if user is None:
        raise NotFoundError("User not found", error_code="user_not_found")
    user.status = payload.status
    await audit.record(
        admin_id=admin.id,
        action="user.status_updated",
        target_type="user",
        target_id=str(user_id),
        metadata={"status": payload.status.value},
    )
    return UserRead.model_validate(user)
