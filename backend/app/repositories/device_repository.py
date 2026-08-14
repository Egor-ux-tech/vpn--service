from sqlalchemy import select

from app.models.device import Device
from app.models.enums import DeviceStatus
from app.repositories.base import BaseRepository


class DeviceRepository(BaseRepository[Device]):
    model = Device

    async def list_for_user(self, user_id: int, *, include_revoked: bool = False) -> list[Device]:
        stmt = select(Device).where(Device.user_id == user_id)
        if not include_revoked:
            stmt = stmt.where(Device.status != DeviceStatus.REVOKED)
        stmt = stmt.order_by(Device.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active_for_user(self, user_id: int) -> int:
        return await self.count(user_id=user_id, status=DeviceStatus.ACTIVE)

    async def get_by_public_key(self, public_key: str) -> Device | None:
        stmt = select(Device).where(Device.public_key == public_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
