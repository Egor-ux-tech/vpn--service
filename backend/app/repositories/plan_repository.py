from sqlalchemy import select

from app.models.plan import Plan
from app.repositories.base import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def get_by_slug(self, slug: str) -> Plan | None:
        stmt = select(Plan).where(Plan.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Plan]:
        stmt = select(Plan).where(Plan.active.is_(True)).order_by(Plan.price)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
