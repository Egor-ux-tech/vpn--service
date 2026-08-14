from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import VPNPeerStatus

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.vpn_server import VPNServer


class VPNPeer(Base, TimestampMixin):
    """Operational/lifecycle record of a WireGuard peer. Never stores the private key."""

    __tablename__ = "vpn_peers"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("vpn_servers.id", ondelete="CASCADE"))
    public_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    assigned_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[VPNPeerStatus] = mapped_column(
        Enum(VPNPeerStatus, native_enum=False), default=VPNPeerStatus.ACTIVE, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="peers")
    server: Mapped["VPNServer"] = relationship()

    __table_args__ = (
        # The actual arbiter for concurrent IP allocation on the same server — application
        # code only ever picks a *candidate* free IP (see ip_allocator.py); this constraint
        # is what turns a lost race into a clean, catchable IntegrityError instead of two
        # peers silently sharing one IP. See DeviceService._create_peer_with_retry.
        UniqueConstraint("server_id", "assigned_ip", name="uq_vpn_peer_server_assigned_ip"),
    )
