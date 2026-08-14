from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import DbSession, get_audit_log_repository, require_admin_role
from app.models.enums import AdminRole
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.admin import DashboardStats
from app.schemas.audit import AuditLogRead
from app.schemas.common import Pagination
from app.services.stats_service import compute_dashboard_counts

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[
        Depends(require_admin_role(AdminRole.SUPERADMIN, AdminRole.SUPPORT, AdminRole.VIEWER))
    ],
)


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(db: DbSession) -> DashboardStats:
    counts = await compute_dashboard_counts(db)
    return DashboardStats(
        total_users=counts.total_users,
        active_subscriptions=counts.active_subscriptions,
        active_devices=counts.active_devices,
        online_servers=counts.online_servers,
        online_peers=counts.online_peers,
        revenue_last_30d=counts.revenue_last_30d,
        open_support_tickets=counts.open_support_tickets,
    )


@router.get("/audit-logs", response_model=list[AuditLogRead])
async def list_audit_logs(
    repo: Annotated[AuditLogRepository, Depends(get_audit_log_repository)],
    pagination: Annotated[Pagination, Depends()],
) -> list[AuditLogRead]:
    logs = await repo.list(offset=pagination.offset, limit=pagination.limit)
    return [AuditLogRead.model_validate(log) for log in logs]
