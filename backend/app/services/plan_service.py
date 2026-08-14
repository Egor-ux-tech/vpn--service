from app.core.errors import ConflictError, NotFoundError
from app.models.plan import Plan
from app.repositories.plan_repository import PlanRepository
from app.schemas.plan import PlanCreate, PlanUpdate


class PlanService:
    def __init__(self, plan_repository: PlanRepository) -> None:
        self._plans = plan_repository

    async def list_active(self) -> list[Plan]:
        return await self._plans.list_active()

    async def get(self, plan_id: int) -> Plan:
        plan = await self._plans.get(plan_id)
        if plan is None:
            raise NotFoundError("Plan not found", error_code="plan_not_found")
        return plan

    async def create(self, payload: PlanCreate) -> Plan:
        if await self._plans.get_by_slug(payload.slug) is not None:
            raise ConflictError("Plan slug already exists", error_code="plan_slug_taken")
        plan = Plan(**payload.model_dump())
        self._plans.add(plan)
        await self._plans.flush()
        return plan

    async def update(self, plan_id: int, payload: PlanUpdate) -> Plan:
        plan = await self.get(plan_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(plan, field, value)
        await self._plans.flush()
        return plan
