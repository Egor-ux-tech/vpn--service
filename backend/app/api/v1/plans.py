from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import get_audit_service, get_current_admin, get_plan_service, require_admin_role
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.schemas.plan import PlanCreate, PlanRead, PlanUpdate
from app.services.audit_service import AuditService
from app.services.plan_service import PlanService

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanRead])
async def list_plans(service: Annotated[PlanService, Depends(get_plan_service)]) -> list[PlanRead]:
    plans = await service.list_active()
    return [PlanRead.model_validate(p) for p in plans]


@router.get("/{plan_id}", response_model=PlanRead)
async def get_plan(
    plan_id: int, service: Annotated[PlanService, Depends(get_plan_service)]
) -> PlanRead:
    return PlanRead.model_validate(await service.get(plan_id))


@router.post(
    "",
    response_model=PlanRead,
    status_code=201,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def create_plan(
    payload: PlanCreate,
    service: Annotated[PlanService, Depends(get_plan_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> PlanRead:
    plan = await service.create(payload)
    await audit.record(
        admin_id=admin.id, action="plan.created", target_type="plan", target_id=str(plan.id)
    )
    return PlanRead.model_validate(plan)


@router.patch(
    "/{plan_id}",
    response_model=PlanRead,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def update_plan(
    plan_id: int,
    payload: PlanUpdate,
    service: Annotated[PlanService, Depends(get_plan_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> PlanRead:
    plan = await service.update(plan_id, payload)
    await audit.record(
        admin_id=admin.id, action="plan.updated", target_type="plan", target_id=str(plan_id)
    )
    return PlanRead.model_validate(plan)
