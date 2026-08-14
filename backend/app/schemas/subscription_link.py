from datetime import datetime

from pydantic import BaseModel

from app.models.enums import SubscriptionLinkStatus
from app.schemas.common import ORMModel


class SubscriptionLinkRead(ORMModel):
    """Deliberately excludes the link's own database id (see "do not expose internal
    database ids unnecessarily") and the token itself — only its hash is ever stored, so
    the plaintext cannot be shown again after creation/rotation; see
    SubscriptionLinkCreated for the one response that does carry it."""

    device_id: int
    status: SubscriptionLinkStatus
    token_prefix: str
    created_at: datetime
    rotated_at: datetime | None
    revoked_at: datetime | None
    last_accessed_at: datetime | None


class SubscriptionLinkCreated(BaseModel):
    """Returned only from POST (create-or-rotate) — the one time the plaintext token/URL
    is ever available. Not retrievable again via GET; rotate again to get a new one."""

    link: SubscriptionLinkRead
    subscription_url: str
    qr_code_base64: str
