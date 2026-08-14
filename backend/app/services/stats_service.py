"""Shared aggregate counts used by both the admin dashboard (JSON) and the /metrics
endpoint (Prometheus gauges) — one query set, two presentations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.enums import (
    DeviceStatus,
    PaymentStatus,
    SubscriptionStatus,
    SupportTicketStatus,
    VPNPeerStatus,
    VPNServerStatus,
)
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.support import SupportTicket
from app.models.user import User
from app.models.vpn_peer import VPNPeer
from app.models.vpn_server import VPNServer


@dataclass(frozen=True, slots=True)
class DashboardCounts:
    total_users: int
    active_subscriptions: int
    active_devices: int
    online_servers: int
    online_peers: int
    revenue_last_30d: float
    open_support_tickets: int


async def _scalar_count(db: AsyncSession, stmt: Select) -> int:
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def compute_dashboard_counts(db: AsyncSession) -> DashboardCounts:
    total_users = await _scalar_count(db, select(func.count()).select_from(User))
    active_subscriptions = await _scalar_count(
        db,
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == SubscriptionStatus.ACTIVE),
    )
    active_devices = await _scalar_count(
        db, select(func.count()).select_from(Device).where(Device.status == DeviceStatus.ACTIVE)
    )
    online_servers = await _scalar_count(
        db,
        select(func.count())
        .select_from(VPNServer)
        .where(VPNServer.status == VPNServerStatus.ONLINE),
    )
    online_peers = await _scalar_count(
        db, select(func.count()).select_from(VPNPeer).where(VPNPeer.status == VPNPeerStatus.ACTIVE)
    )
    open_tickets = await _scalar_count(
        db,
        select(func.count())
        .select_from(SupportTicket)
        .where(SupportTicket.status.in_([SupportTicketStatus.OPEN, SupportTicketStatus.PENDING])),
    )

    since = datetime.now(UTC) - timedelta(days=30)
    revenue_result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == PaymentStatus.SUCCEEDED, Payment.created_at >= since
        )
    )
    revenue = revenue_result.scalar_one()

    return DashboardCounts(
        total_users=total_users,
        active_subscriptions=active_subscriptions,
        active_devices=active_devices,
        online_servers=online_servers,
        online_peers=online_peers,
        revenue_last_30d=float(revenue or Decimal("0")),
        open_support_tickets=open_tickets,
    )
