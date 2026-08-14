from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import RouteType, RoutingMode


class RoutingCategory(Base):
    """Global catalog category, e.g. 'Video', 'Messengers' — managed by admins."""

    __tablename__ = "routing_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RoutingRule(Base):
    """Global domain -> category catalog entry, e.g. youtube.com in 'Video'."""

    __tablename__ = "routing_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("routing_categories.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    route_type: Mapped[RouteType] = mapped_column(
        Enum(RouteType, native_enum=False), default=RouteType.VPN, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    category: Mapped["RoutingCategory"] = relationship()

    __table_args__ = (UniqueConstraint("category_id", "domain", name="uq_routing_rule_domain"),)


class UserRoutingProfile(Base):
    """Per-user routing mode selection: FULL_VPN or SMART_VPN."""

    __tablename__ = "user_routing_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    mode: Mapped[RoutingMode] = mapped_column(
        Enum(RoutingMode, native_enum=False), default=RoutingMode.FULL_VPN, nullable=False
    )


class UserCategoryPreference(Base):
    """Whether a given user routes a whole category via VPN or DIRECT (SMART_VPN mode only)."""

    __tablename__ = "user_category_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("routing_categories.id", ondelete="CASCADE")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped["RoutingCategory"] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "category_id", name="uq_user_category_preference"),
    )


class UserCustomDomain(Base):
    """A user-added domain outside the global catalog, e.g. their own work VPN target."""

    __tablename__ = "user_custom_domains"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    route_type: Mapped[RouteType] = mapped_column(
        Enum(RouteType, native_enum=False), default=RouteType.VPN, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "domain", name="uq_user_custom_domain"),)
