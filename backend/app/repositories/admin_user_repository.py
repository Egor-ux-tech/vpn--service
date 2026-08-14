from sqlalchemy import func, select

from app.models.admin_user import AdminUser
from app.repositories.base import BaseRepository


class AdminUserRepository(BaseRepository[AdminUser]):
    model = AdminUser

    async def get_by_email(self, email: str) -> AdminUser | None:
        stmt = select(AdminUser).where(AdminUser.email == email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_all(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(AdminUser))
        return int(result.scalar_one())
