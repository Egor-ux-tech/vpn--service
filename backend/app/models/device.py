from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import DeviceStatus, VPNProtocol

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vpn_peer import VPNPeer
    from app.models.vpn_server import VPNServer


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # WireGuard-specific — always None for protocol=vless devices, whose credentials
    # live entirely in VLESSCredential (see app/models/vless_credential.py) rather than
    # being forced into these columns.
    public_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    assigned_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    server_id: Mapped[int | None] = mapped_column(
        ForeignKey("vpn_servers.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False), default=DeviceStatus.ACTIVE, nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    protocol: Mapped[VPNProtocol] = mapped_column(
        Enum(VPNProtocol, native_enum=False), default=VPNProtocol.WIREGUARD, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="devices")
    server: Mapped["VPNServer | None"] = relationship()
    peers: Mapped[list["VPNPeer"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
