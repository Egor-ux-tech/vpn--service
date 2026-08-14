from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import VPNProtocol, VPNServerStatus


class VPNServer(Base, TimestampMixin):
    __tablename__ = "vpn_servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    # WireGuard-specific fields below (agent_base_url/public_key/endpoint/listen_port/
    # internal_network) stay exactly as-is and are always meaningless/unused for
    # protocol=vless rows — VLESS's equivalent server-side data lives entirely in the
    # separate VLESSServerConfig table (see app/models/vless_server_config.py), never
    # forced into these columns. See docs/vless.md.
    agent_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    listen_port: Mapped[int] = mapped_column(Integer, default=51820, nullable=False)
    internal_network: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[VPNServerStatus] = mapped_column(
        Enum(VPNServerStatus, native_enum=False),
        default=VPNServerStatus.OFFLINE,
        nullable=False,
        index=True,
    )
    capacity: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    current_load: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    protocol: Mapped[VPNProtocol] = mapped_column(
        Enum(VPNProtocol, native_enum=False),
        default=VPNProtocol.WIREGUARD,
        nullable=False,
        index=True,
    )
