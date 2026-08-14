from datetime import UTC, datetime

from app.models.audit_log import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository


class AuditService:
    def __init__(self, audit_repository: AuditLogRepository) -> None:
        self._logs = audit_repository

    async def record(
        self,
        *,
        admin_id: int | None,
        action: str,
        target_type: str,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        log = AuditLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
            created_at=datetime.now(UTC),
        )
        self._logs.add(log)
        await self._logs.flush()
        return log
