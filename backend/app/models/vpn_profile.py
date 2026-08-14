from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import RoutingMode

if TYPE_CHECKING:
    from app.models.device import Device


class VPNProfile(Base, TimestampMixin):
    """A versioned snapshot of the routing rules (AllowedIPs/DNS) for one device's peer."""

    __tablename__ = "vpn_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    mode: Mapped[RoutingMode] = mapped_column(
        Enum(RoutingMode, native_enum=False), default=RoutingMode.FULL_VPN, nullable=False
    )
    allowed_ips: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    device: Mapped["Device"] = relationship()
