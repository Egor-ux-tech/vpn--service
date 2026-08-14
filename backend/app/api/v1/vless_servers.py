"""Admin registration for VLESS exit nodes — a separate router/namespace from
api/v1/servers.py (WireGuard), left completely untouched (see docs/vless.md). Creating
a VLESS server here creates its VPNServer + VLESSServerConfig rows together in one call,
so an admin never has to understand or supply meaningless WireGuard-only fields by hand.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    get_audit_service,
    get_current_admin,
    get_vless_server_service,
    require_admin_role,
)
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.models.vless_server_config import VLESSServerConfig
from app.models.vpn_server import VPNServer
from app.schemas.vless import VLESSServerCreate, VLESSServerRead, VLESSServerUpdate
from app.services.audit_service import AuditService
from app.services.vless_server_service import VLESSServerService

router = APIRouter(prefix="/vless-servers", tags=["vless-servers"])


def _to_read(server: VPNServer, config: VLESSServerConfig) -> VLESSServerRead:
    return VLESSServerRead(
        id=server.id,
        name=server.name,
        country=server.country,
        city=server.city,
        hostname=server.hostname,
        status=server.status,
        capacity=server.capacity,
        current_load=server.current_load,
        xray_agent_base_url=config.xray_agent_base_url,
        port=config.port,
        reality_public_key=config.reality_public_key,
        reality_short_ids=config.reality_short_ids,
        sni=config.sni,
        fingerprint=config.fingerprint,
        flow=config.flow,
        network_type=config.network_type,
    )


@router.get("", response_model=list[VLESSServerRead])
async def list_vless_servers(
    service: Annotated[VLESSServerService, Depends(get_vless_server_service)],
) -> list[VLESSServerRead]:
    pairs = await service.list()
    return [_to_read(server, config) for server, config in pairs]


@router.post(
    "",
    response_model=VLESSServerRead,
    status_code=201,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def create_vless_server(
    payload: VLESSServerCreate,
    service: Annotated[VLESSServerService, Depends(get_vless_server_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> VLESSServerRead:
    server, config = await service.create(payload)
    await audit.record(
        admin_id=admin.id,
        action="vless_server.created",
        target_type="vpn_server",
        target_id=str(server.id),
    )
    return _to_read(server, config)


@router.patch(
    "/{server_id}",
    response_model=VLESSServerRead,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def update_vless_server(
    server_id: int,
    payload: VLESSServerUpdate,
    service: Annotated[VLESSServerService, Depends(get_vless_server_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> VLESSServerRead:
    server, config = await service.update(server_id, payload)
    await audit.record(
        admin_id=admin.id,
        action="vless_server.updated",
        target_type="vpn_server",
        target_id=str(server_id),
    )
    return _to_read(server, config)


@router.delete(
    "/{server_id}",
    status_code=204,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def delete_vless_server(
    server_id: int,
    service: Annotated[VLESSServerService, Depends(get_vless_server_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> None:
    await service.delete(server_id)
    await audit.record(
        admin_id=admin.id,
        action="vless_server.deleted",
        target_type="vpn_server",
        target_id=str(server_id),
    )
