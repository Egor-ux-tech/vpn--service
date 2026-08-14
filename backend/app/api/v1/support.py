from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import (
    get_audit_service,
    get_current_admin,
    get_current_user,
    get_support_service,
    require_admin_role,
)
from app.core.errors import PermissionDeniedError
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole, SupportSender
from app.models.user import User
from app.schemas.common import Pagination
from app.schemas.support import (
    SupportMessageCreate,
    SupportMessageRead,
    SupportTicketCreate,
    SupportTicketRead,
)
from app.services.audit_service import AuditService
from app.services.support_service import SupportService

router = APIRouter(prefix="/support", tags=["support"])


@router.post("", response_model=SupportTicketRead, status_code=201)
async def create_ticket(
    payload: SupportTicketCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> SupportTicketRead:
    ticket = await service.create_ticket(
        user_id=user.id, subject=payload.subject, message=payload.message
    )
    return SupportTicketRead.model_validate(ticket)


@router.get("/me", response_model=list[SupportTicketRead])
async def list_my_tickets(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> list[SupportTicketRead]:
    tickets = await service.list_for_user(user.id)
    return [SupportTicketRead.model_validate(t) for t in tickets]


@router.get(
    "",
    response_model=list[SupportTicketRead],
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT))],
)
async def list_all_tickets(
    service: Annotated[SupportService, Depends(get_support_service)],
    pagination: Annotated[Pagination, Depends()],
) -> list[SupportTicketRead]:
    tickets = await service.list_all(offset=pagination.offset, limit=pagination.limit)
    return [SupportTicketRead.model_validate(t) for t in tickets]


@router.get("/{ticket_id}", response_model=SupportTicketRead)
async def get_ticket(
    ticket_id: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> SupportTicketRead:
    ticket = await service.get(ticket_id)
    if ticket.user_id != user.id:
        raise PermissionDeniedError("Not your ticket", error_code="not_your_ticket")
    return SupportTicketRead.model_validate(ticket)


@router.post("/{ticket_id}/messages", response_model=SupportMessageRead, status_code=201)
async def add_message(
    ticket_id: int,
    payload: SupportMessageCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> SupportMessageRead:
    ticket = await service.get(ticket_id)
    if ticket.user_id != user.id:
        raise PermissionDeniedError("Not your ticket", error_code="not_your_ticket")
    message = await service.add_message(ticket, sender=SupportSender.USER, text=payload.text)
    return SupportMessageRead.model_validate(message)


@router.post(
    "/{ticket_id}/reply",
    response_model=SupportMessageRead,
    status_code=201,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT))],
)
async def admin_reply(
    ticket_id: int,
    payload: SupportMessageCreate,
    service: Annotated[SupportService, Depends(get_support_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> SupportMessageRead:
    ticket = await service.get(ticket_id)
    message = await service.add_message(ticket, sender=SupportSender.ADMIN, text=payload.text)
    await audit.record(
        admin_id=admin.id,
        action="support_ticket.replied",
        target_type="support_ticket",
        target_id=str(ticket_id),
    )
    return SupportMessageRead.model_validate(message)


@router.post(
    "/{ticket_id}/close",
    response_model=SupportTicketRead,
    dependencies=[Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT))],
)
async def close_ticket(
    ticket_id: int,
    service: Annotated[SupportService, Depends(get_support_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    admin: Annotated[AdminUser, Depends(get_current_admin)],
) -> SupportTicketRead:
    ticket = await service.get(ticket_id)
    ticket = await service.close(ticket)
    await audit.record(
        admin_id=admin.id,
        action="support_ticket.closed",
        target_type="support_ticket",
        target_id=str(ticket_id),
    )
    return SupportTicketRead.model_validate(ticket)
