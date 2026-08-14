from sqlalchemy import select

from app.models.enums import VLESSCredentialStatus
from app.models.vless_credential import VLESSCredential
from app.repositories.base import BaseRepository


class VLESSCredentialRepository(BaseRepository[VLESSCredential]):
    model = VLESSCredential

    async def get_active_for_device_and_server(
        self, device_id: int, server_id: int
    ) -> VLESSCredential | None:
        stmt = select(VLESSCredential).where(
            VLESSCredential.device_id == device_id,
            VLESSCredential.server_id == server_id,
            VLESSCredential.status == VLESSCredentialStatus.ACTIVE,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_for_device(self, device_id: int) -> list[VLESSCredential]:
        """Every live credential for a device, across however many VLESS servers it has
        one on — see VLESSFormatter, which renders one `vless://` line per row."""
        stmt = select(VLESSCredential).where(
            VLESSCredential.device_id == device_id,
            VLESSCredential.status == VLESSCredentialStatus.ACTIVE,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_device(self, device_id: int) -> list[VLESSCredential]:
        stmt = select(VLESSCredential).where(VLESSCredential.device_id == device_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
