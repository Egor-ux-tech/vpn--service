from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    get_audit_service,
    get_current_admin,
    get_vpn_server_service,
    require_admin_role,
)
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.schemas.vpn import VPNServerCreate, VPNServerRead, VPNServerUpdate
from app.services.audit_service import AuditService
from app.services.vpn_server_service import VPNServerService

router = APIRouter(prefix="/servers", tags=["servers"])


@router.get("", response_model=list[VPNServerRead])
async def list_servers(
    service: Annotated[VPNServerService, Depends(get_vpn_server_service)],
) -> list[VPNServerRead]:
    servers = await service.list()
    return [VPNServerRead.model_validate(s) for s in servers]


@router.post(
    "",
    response_model=VPNServerRead,
    status_code=201,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def create_server(
    payload: VPNServerCreate,
    service: Annotated[VPNServerService, Depends(get_vpn_server_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> VPNServerRead:
    server = await service.create(payload)
    await audit.record(
        admin_id=admin.id,
        action="server.created",
        target_type="vpn_server",
        target_id=str(server.id),
    )
    return VPNServerRead.model_validate(server)


@router.patch(
    "/{server_id}",
    response_model=VPNServerRead,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def update_server(
    server_id: int,
    payload: VPNServerUpdate,
    service: Annotated[VPNServerService, Depends(get_vpn_server_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> VPNServerRead:
    server = await service.update(server_id, payload)
    await audit.record(
        admin_id=admin.id,
        action="server.updated",
        target_type="vpn_server",
        target_id=str(server_id),
    )
    return VPNServerRead.model_validate(server)


@router.delete(
    "/{server_id}",
    status_code=204,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN))],
)
async def delete_server(
    server_id: int,
    service: Annotated[VPNServerService, Depends(get_vpn_server_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> None:
    await service.delete(server_id)
    await audit.record(
        admin_id=admin.id,
        action="server.deleted",
        target_type="vpn_server",
        target_id=str(server_id),
    )
