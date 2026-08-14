from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AuditLogCreate(BaseModel):
    admin_id: int | None
    action: str
    target_type: str
    target_id: str | None = None
    metadata_json: dict = {}


class AuditLogRead(ORMModel):
    id: int
    admin_id: int | None
    action: str
    target_type: str
    target_id: str | None
    metadata_json: dict
    created_at: datetime
