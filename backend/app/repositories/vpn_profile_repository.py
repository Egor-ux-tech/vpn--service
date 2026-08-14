from sqlalchemy import select, update

from app.models.vpn_profile import VPNProfile
from app.repositories.base import BaseRepository


class VPNProfileRepository(BaseRepository[VPNProfile]):
    model = VPNProfile

    async def get_current_for_device(self, device_id: int) -> VPNProfile | None:
        stmt = select(VPNProfile).where(
            VPNProfile.device_id == device_id, VPNProfile.is_current.is_(True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_superseded(self, device_id: int) -> None:
        stmt = (
            update(VPNProfile)
            .where(VPNProfile.device_id == device_id, VPNProfile.is_current.is_(True))
            .values(is_current=False)
        )
        await self.session.execute(stmt)
