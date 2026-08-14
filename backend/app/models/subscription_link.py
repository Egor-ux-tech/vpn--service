from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import SubscriptionLinkStatus

if TYPE_CHECKING:
    from app.models.device import Device


class SubscriptionLink(Base, TimestampMixin):
    """The "subscription URL" a VPN client (WireGuard today, Happ/others later) fetches
    repeatedly to pull a device's current config — distinct from `Subscription` (the
    billing entity in app/models/subscription.py). One per device (1:1 for phase 1; see
    docs/subscription-delivery.md for why a multi-node/account-level link is deliberately
    out of scope here).

    Only `token_hash` (sha256 of the opaque bearer token) is ever stored — the plaintext
    token exists only in memory at creation/rotation time, exactly like a WireGuard private
    key never persisted (see docs/wireguard.md). `token_prefix` is intentionally
    non-secret — just enough for a human to recognize "the link starting with abc123..." in
    logs/support conversations without the full secret ever appearing there.
    """

    __tablename__ = "subscription_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[SubscriptionLinkStatus] = mapped_column(
        Enum(SubscriptionLinkStatus, native_enum=False),
        default=SubscriptionLinkStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    device: Mapped["Device"] = relationship()
