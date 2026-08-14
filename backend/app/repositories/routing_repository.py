from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.routing import (
    RoutingCategory,
    RoutingRule,
    UserCategoryPreference,
    UserCustomDomain,
    UserRoutingProfile,
)
from app.repositories.base import BaseRepository


class RoutingCategoryRepository(BaseRepository[RoutingCategory]):
    model = RoutingCategory

    async def list_enabled(self) -> list[RoutingCategory]:
        stmt = select(RoutingCategory).where(RoutingCategory.enabled.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RoutingRuleRepository(BaseRepository[RoutingRule]):
    model = RoutingRule

    async def list_for_category(self, category_id: int) -> list[RoutingRule]:
        stmt = select(RoutingRule).where(
            RoutingRule.category_id == category_id, RoutingRule.enabled.is_(True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_enabled_with_category(self) -> list[RoutingRule]:
        stmt = (
            select(RoutingRule)
            .where(RoutingRule.enabled.is_(True))
            .options(selectinload(RoutingRule.category))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class UserRoutingProfileRepository(BaseRepository[UserRoutingProfile]):
    model = UserRoutingProfile

    async def get_for_user(self, user_id: int) -> UserRoutingProfile | None:
        stmt = select(UserRoutingProfile).where(UserRoutingProfile.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class UserCategoryPreferenceRepository(BaseRepository[UserCategoryPreference]):
    model = UserCategoryPreference

    async def list_for_user(self, user_id: int) -> list[UserCategoryPreference]:
        stmt = select(UserCategoryPreference).where(UserCategoryPreference.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, user_id: int, category_id: int) -> UserCategoryPreference | None:  # type: ignore[override]
        stmt = select(UserCategoryPreference).where(
            UserCategoryPreference.user_id == user_id,
            UserCategoryPreference.category_id == category_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class UserCustomDomainRepository(BaseRepository[UserCustomDomain]):
    model = UserCustomDomain

    async def list_for_user(self, user_id: int) -> list[UserCustomDomain]:
        stmt = select(UserCustomDomain).where(UserCustomDomain.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
