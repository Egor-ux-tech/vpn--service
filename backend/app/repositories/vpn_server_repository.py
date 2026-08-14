from sqlalchemy import select

from app.models.enums import VPNServerStatus
from app.models.vpn_server import VPNServer
from app.repositories.base import BaseRepository


class VPNServerRepository(BaseRepository[VPNServer]):
    model = VPNServer

    async def list_available(self) -> list[VPNServer]:
        stmt = (
            select(VPNServer)
            .where(VPNServer.status == VPNServerStatus.ONLINE)
            .order_by(VPNServer.current_load)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
