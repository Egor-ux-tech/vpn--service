from app.core.errors import ConflictError, NotFoundError
from app.models.enums import VPNServerStatus
from app.models.vpn_server import VPNServer
from app.repositories.vpn_server_repository import VPNServerRepository
from app.schemas.vpn import VPNServerCreate, VPNServerUpdate


class VPNServerService:
    def __init__(self, server_repository: VPNServerRepository) -> None:
        self._servers = server_repository

    async def list(self) -> list[VPNServer]:
        return await self._servers.list(limit=1000)

    async def get(self, server_id: int) -> VPNServer:
        server = await self._servers.get(server_id)
        if server is None:
            raise NotFoundError("VPN server not found", error_code="vpn_server_not_found")
        return server

    async def create(self, payload: VPNServerCreate) -> VPNServer:
        server = VPNServer(**payload.model_dump(), status=VPNServerStatus.OFFLINE)
        self._servers.add(server)
        await self._servers.flush()
        return server

    async def update(self, server_id: int, payload: VPNServerUpdate) -> VPNServer:
        server = await self.get(server_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(server, field, value)
        await self._servers.flush()
        return server

    async def pick_best_available(self) -> VPNServer:
        candidates = await self._servers.list_available()
        under_capacity = [s for s in candidates if s.current_load < s.capacity]
        if not under_capacity:
            raise ConflictError(
                "No VPN servers with free capacity are currently online",
                error_code="no_capacity_available",
            )
        return under_capacity[0]

    async def delete(self, server_id: int) -> None:
        server = await self.get(server_id)
        await self._servers.delete(server)
