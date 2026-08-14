from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import DeviceStatus

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.vpn_peer import VPNPeer
    from app.models.vpn_server import VPNServer


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    assigned_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    server_id: Mapped[int | None] = mapped_column(
        ForeignKey("vpn_servers.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus, native_enum=False), default=DeviceStatus.ACTIVE, nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="devices")
    server: Mapped["VPNServer | None"] = relationship()
    peers: Mapped[list["VPNPeer"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
