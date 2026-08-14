from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class SubscriptionStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


class VPNServerStatus(StrEnum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


class VPNPeerStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


class RoutingMode(StrEnum):
    FULL_VPN = "full_vpn"
    SMART_VPN = "smart_vpn"


class RouteType(StrEnum):
    VPN = "vpn"
    DIRECT = "direct"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PromoDiscountType(StrEnum):
    PERCENT = "percent"
    FIXED = "fixed"


class SupportTicketStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    CLOSED = "closed"


class SupportSender(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AdminRole(StrEnum):
    SUPERADMIN = "superadmin"
    SUPPORT = "support"
    VIEWER = "viewer"
