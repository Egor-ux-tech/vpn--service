from sqlalchemy import select

from app.models.enums import VPNPeerStatus
from app.models.vpn_peer import VPNPeer
from app.repositories.base import BaseRepository


class VPNPeerRepository(BaseRepository[VPNPeer]):
    model = VPNPeer

    async def get_active_for_device(self, device_id: int) -> VPNPeer | None:
        stmt = (
            select(VPNPeer)
            .where(VPNPeer.device_id == device_id, VPNPeer.status == VPNPeerStatus.ACTIVE)
            .order_by(VPNPeer.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_for_server(self, server_id: int) -> list[VPNPeer]:
        stmt = select(VPNPeer).where(VPNPeer.server_id == server_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
