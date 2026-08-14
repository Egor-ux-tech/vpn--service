"""Registers a VLESS exit node — creates the `VPNServer` row (protocol=vless) and its
1:1 `VLESSServerConfig` together, since the admin-facing concept is "one VLESS server",
even though it spans two tables (see docs/vless.md for why they're separate).

`VPNServer`'s WireGuard-specific NOT NULL columns (agent_base_url, public_key, endpoint,
internal_network) are never altered or repurposed — see app/models/vpn_server.py — so a
VLESS server row fills them with an explicit, clearly-labeled placeholder rather than
asking an admin to understand/supply meaningless WireGuard values by hand.
"""

from app.core.errors import NotFoundError
from app.models.enums import VPNProtocol, VPNServerStatus
from app.models.vless_server_config import VLESSServerConfig
from app.models.vpn_server import VPNServer
from app.repositories.vless_server_config_repository import VLESSServerConfigRepository
from app.repositories.vpn_server_repository import VPNServerRepository
from app.schemas.vless import VLESSServerCreate, VLESSServerUpdate

_UNUSED_FOR_VLESS = "unused-for-vless"


class VLESSServerService:
    def __init__(
        self,
        server_repository: VPNServerRepository,
        config_repository: VLESSServerConfigRepository,
    ) -> None:
        self._servers = server_repository
        self._configs = config_repository

    async def list(self) -> list[tuple[VPNServer, VLESSServerConfig]]:
        servers = await self._servers.list(limit=1000, protocol=VPNProtocol.VLESS)
        result = []
        for server in servers:
            config = await self._configs.get_for_server(server.id)
            if config is not None:
                result.append((server, config))
        return result

    async def get(self, server_id: int) -> tuple[VPNServer, VLESSServerConfig]:
        server = await self._servers.get(server_id)
        if server is None or server.protocol is not VPNProtocol.VLESS:
            raise NotFoundError("VLESS server not found", error_code="vless_server_not_found")
        config = await self._configs.get_for_server(server_id)
        if config is None:
            raise NotFoundError(
                "VLESS server has no Reality configuration", error_code="vless_server_not_found"
            )
        return server, config

    async def create(self, payload: VLESSServerCreate) -> tuple[VPNServer, VLESSServerConfig]:
        server = VPNServer(
            name=payload.name,
            country=payload.country,
            city=payload.city,
            hostname=payload.hostname,
            capacity=payload.capacity,
            status=VPNServerStatus.OFFLINE,
            protocol=VPNProtocol.VLESS,
            agent_base_url=_UNUSED_FOR_VLESS,
            public_key=_UNUSED_FOR_VLESS,
            endpoint=_UNUSED_FOR_VLESS,
            internal_network="0.0.0.0/32",
        )
        self._servers.add(server)
        await self._servers.flush()

        config = VLESSServerConfig(
            server_id=server.id,
            xray_agent_base_url=payload.xray_agent_base_url,
            port=payload.port,
            reality_public_key=payload.reality_public_key,
            reality_short_ids=payload.reality_short_ids,
            sni=payload.sni,
            fingerprint=payload.fingerprint,
            flow=payload.flow,
            network_type=payload.network_type,
        )
        self._configs.add(config)
        await self._configs.flush()
        return server, config

    async def update(
        self, server_id: int, payload: VLESSServerUpdate
    ) -> tuple[VPNServer, VLESSServerConfig]:
        server, config = await self.get(server_id)
        server_fields = {"status", "capacity", "name"}
        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            if field in server_fields:
                setattr(server, field, value)
            else:
                setattr(config, field, value)
        await self._servers.flush()
        await self._configs.flush()
        return server, config

    async def delete(self, server_id: int) -> None:
        server, config = await self.get(server_id)
        await self._configs.delete(config)
        await self._servers.delete(server)
