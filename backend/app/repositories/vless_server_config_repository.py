from sqlalchemy import select

from app.models.vless_server_config import VLESSServerConfig
from app.repositories.base import BaseRepository


class VLESSServerConfigRepository(BaseRepository[VLESSServerConfig]):
    model = VLESSServerConfig

    async def get_for_server(self, server_id: int) -> VLESSServerConfig | None:
        stmt = select(VLESSServerConfig).where(VLESSServerConfig.server_id == server_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
