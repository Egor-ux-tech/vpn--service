from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    get_audit_service,
    get_current_admin,
    get_current_user,
    get_routing_service,
    require_admin_role,
)
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.models.user import User
from app.schemas.routing import (
    RoutingCategoryCreate,
    RoutingCategoryRead,
    RoutingRuleCreate,
    RoutingRuleRead,
    UserCategoryPreferenceUpdate,
    UserCustomDomainCreate,
    UserRoutingModeUpdate,
    UserRoutingSettingsRead,
)
from app.services.audit_service import AuditService
from app.services.routing_service import RoutingService

router = APIRouter(prefix="/routing", tags=["routing"])


@router.get("/categories", response_model=list[RoutingCategoryRead])
async def list_categories(
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> list[RoutingCategoryRead]:
    categories = await service.list_categories()
    return [RoutingCategoryRead.model_validate(c) for c in categories]


@router.post(
    "/categories",
    response_model=RoutingCategoryRead,
    status_code=201,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def create_category(
    payload: RoutingCategoryCreate,
    service: Annotated[RoutingService, Depends(get_routing_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> RoutingCategoryRead:
    category = await service.create_category(payload.name, payload.description)
    await audit.record(
        admin_id=admin.id,
        action="routing_category.created",
        target_type="routing_category",
        target_id=str(category.id),
    )
    return RoutingCategoryRead.model_validate(category)


@router.post(
    "/rules",
    response_model=RoutingRuleRead,
    status_code=201,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def add_rule(
    payload: RoutingRuleCreate, service: Annotated[RoutingService, Depends(get_routing_service)]
) -> RoutingRuleRead:
    rule = await service.add_rule(payload)
    return RoutingRuleRead.model_validate(rule)


@router.get("/me/settings", response_model=UserRoutingSettingsRead)
async def get_my_routing_settings(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> UserRoutingSettingsRead:
    profile = await service.get_or_create_user_profile(user.id)
    categories = await service.list_categories()
    prefs = await service.list_user_category_preferences(user.id)
    custom_domains = await service.list_user_custom_domains(user.id)
    return UserRoutingSettingsRead(
        mode=profile.mode,
        categories=[RoutingCategoryRead.model_validate(c) for c in categories],
        enabled_category_ids=[p.category_id for p in prefs if p.enabled],
        custom_domains=[d.domain for d in custom_domains if d.enabled],
    )


@router.put("/me/mode", response_model=UserRoutingSettingsRead)
async def set_my_routing_mode(
    payload: UserRoutingModeUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> UserRoutingSettingsRead:
    await service.set_mode(user.id, payload.mode)
    return await get_my_routing_settings(user, service)


@router.put("/me/categories", response_model=UserRoutingSettingsRead)
async def set_my_category_preference(
    payload: UserCategoryPreferenceUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> UserRoutingSettingsRead:
    await service.set_category_preference(user.id, payload.category_id, payload.enabled)
    return await get_my_routing_settings(user, service)


@router.post("/me/domains", response_model=UserRoutingSettingsRead)
async def add_my_custom_domain(
    payload: UserCustomDomainCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RoutingService, Depends(get_routing_service)],
) -> UserRoutingSettingsRead:
    await service.add_custom_domain(user.id, payload.domain, payload.route_type)
    return await get_my_routing_settings(user, service)
