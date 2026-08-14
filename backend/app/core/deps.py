from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import PermissionDeniedError, UnauthorizedError
from app.core.security import constant_time_compare, decode_token
from app.db.session import get_db
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.models.user import User
from app.repositories.admin_user_repository import AdminUserRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.promo_code_repository import (
    PromoCodeRedemptionRepository,
    PromoCodeRepository,
)
from app.repositories.referral_repository import ReferralRepository
from app.repositories.routing_repository import (
    RoutingCategoryRepository,
    RoutingRuleRepository,
    UserCategoryPreferenceRepository,
    UserCustomDomainRepository,
    UserRoutingProfileRepository,
)
from app.repositories.subscription_link_repository import SubscriptionLinkRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.support_repository import SupportMessageRepository, SupportTicketRepository
from app.repositories.user_repository import UserRepository
from app.repositories.vless_credential_repository import VLESSCredentialRepository
from app.repositories.vless_server_config_repository import VLESSServerConfigRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.repositories.vpn_server_repository import VPNServerRepository
from app.services.admin_auth_service import AdminAuthService
from app.services.audit_service import AuditService
from app.services.device_service import DeviceService
from app.services.notifications.bot_notifier import BotNotifier
from app.services.notifications.provider import NotificationProvider
from app.services.payment_service import PaymentService
from app.services.payments.mock_provider import MockPaymentProvider
from app.services.payments.provider import PaymentProvider
from app.services.plan_service import PlanService
from app.services.referral_service import ReferralService
from app.services.routing.dns_resolver import DomainResolver
from app.services.routing.engine import RoutingEngine
from app.services.routing_service import RoutingService
from app.services.subscription_delivery.delivery_service import SubscriptionDeliveryService
from app.services.subscription_delivery.formatters.base import SubscriptionFormatter
from app.services.subscription_delivery.formatters.vless_formatter import VLESSFormatter
from app.services.subscription_delivery.formatters.wireguard_formatter import WireGuardFormatter
from app.services.subscription_link_service import SubscriptionLinkService
from app.services.subscription_service import SubscriptionService
from app.services.support_service import SupportService
from app.services.user_service import UserService
from app.services.vless.provider import XrayAgentProvider
from app.services.vless.xray_agent_provider import HttpXrayAgentProvider
from app.services.vless_server_service import VLESSServerService
from app.services.vpn.provider import VPNProvider
from app.services.vpn.wireguard_provider import WireGuardProvider
from app.services.vpn_server_service import VPNServerService

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---- Repositories ----


def get_user_repository(db: DbSession) -> UserRepository:
    return UserRepository(db)


def get_plan_repository(db: DbSession) -> PlanRepository:
    return PlanRepository(db)


def get_subscription_repository(db: DbSession) -> SubscriptionRepository:
    return SubscriptionRepository(db)


def get_device_repository(db: DbSession) -> DeviceRepository:
    return DeviceRepository(db)


def get_vpn_server_repository(db: DbSession) -> VPNServerRepository:
    return VPNServerRepository(db)


def get_vpn_peer_repository(db: DbSession) -> VPNPeerRepository:
    return VPNPeerRepository(db)


def get_vpn_profile_repository(db: DbSession) -> VPNProfileRepository:
    return VPNProfileRepository(db)


def get_routing_category_repository(db: DbSession) -> RoutingCategoryRepository:
    return RoutingCategoryRepository(db)


def get_routing_rule_repository(db: DbSession) -> RoutingRuleRepository:
    return RoutingRuleRepository(db)


def get_user_routing_profile_repository(db: DbSession) -> UserRoutingProfileRepository:
    return UserRoutingProfileRepository(db)


def get_user_category_pref_repository(db: DbSession) -> UserCategoryPreferenceRepository:
    return UserCategoryPreferenceRepository(db)


def get_user_custom_domain_repository(db: DbSession) -> UserCustomDomainRepository:
    return UserCustomDomainRepository(db)


def get_payment_repository(db: DbSession) -> PaymentRepository:
    return PaymentRepository(db)


def get_promo_code_repository(db: DbSession) -> PromoCodeRepository:
    return PromoCodeRepository(db)


def get_promo_redemption_repository(db: DbSession) -> PromoCodeRedemptionRepository:
    return PromoCodeRedemptionRepository(db)


def get_support_ticket_repository(db: DbSession) -> SupportTicketRepository:
    return SupportTicketRepository(db)


def get_support_message_repository(db: DbSession) -> SupportMessageRepository:
    return SupportMessageRepository(db)


def get_audit_log_repository(db: DbSession) -> AuditLogRepository:
    return AuditLogRepository(db)


def get_admin_user_repository(db: DbSession) -> AdminUserRepository:
    return AdminUserRepository(db)


def get_referral_repository(db: DbSession) -> ReferralRepository:
    return ReferralRepository(db)


def get_subscription_link_repository(db: DbSession) -> SubscriptionLinkRepository:
    return SubscriptionLinkRepository(db)


def get_vless_credential_repository(db: DbSession) -> VLESSCredentialRepository:
    return VLESSCredentialRepository(db)


def get_vless_server_config_repository(db: DbSession) -> VLESSServerConfigRepository:
    return VLESSServerConfigRepository(db)


# ---- Cross-cutting providers ----


def get_vpn_provider(settings: SettingsDep) -> VPNProvider:
    return WireGuardProvider(
        shared_secret=settings.vpn_agent_shared_secret, dns_servers=settings.vpn_dns_list
    )


def get_xray_agent_provider(settings: SettingsDep) -> XrayAgentProvider:
    return HttpXrayAgentProvider(shared_secret=settings.xray_agent_shared_secret)


def get_payment_provider(settings: SettingsDep) -> PaymentProvider:
    if settings.payment_provider == "mock":
        return MockPaymentProvider(webhook_secret=settings.payment_webhook_secret)
    # Future real providers (YooKassa/Cryptomus/Stripe) plug in here via the same interface.
    raise NotImplementedError(f"Unsupported payment provider: {settings.payment_provider}")


def get_notification_provider(settings: SettingsDep) -> NotificationProvider:
    return BotNotifier(
        bot_notify_base_url=settings.bot_notify_base_url,
        internal_service_token=settings.internal_service_token,
    )


def get_domain_resolver(settings: SettingsDep) -> DomainResolver:
    return DomainResolver(nameservers=settings.vpn_dns_list)


def get_routing_engine(
    resolver: Annotated[DomainResolver, Depends(get_domain_resolver)],
) -> RoutingEngine:
    return RoutingEngine(resolver)


# ---- Services ----


def get_user_service(repo: Annotated[UserRepository, Depends(get_user_repository)]) -> UserService:
    return UserService(repo)


def get_plan_service(repo: Annotated[PlanRepository, Depends(get_plan_repository)]) -> PlanService:
    return PlanService(repo)


def get_subscription_service(
    repo: Annotated[SubscriptionRepository, Depends(get_subscription_repository)],
) -> SubscriptionService:
    return SubscriptionService(repo)


def get_vpn_server_service(
    repo: Annotated[VPNServerRepository, Depends(get_vpn_server_repository)],
) -> VPNServerService:
    return VPNServerService(repo)


def get_vless_server_service(
    server_repo: Annotated[VPNServerRepository, Depends(get_vpn_server_repository)],
    config_repo: Annotated[
        VLESSServerConfigRepository, Depends(get_vless_server_config_repository)
    ],
) -> VLESSServerService:
    return VLESSServerService(server_repo, config_repo)


def get_routing_service(
    category_repo: Annotated[RoutingCategoryRepository, Depends(get_routing_category_repository)],
    rule_repo: Annotated[RoutingRuleRepository, Depends(get_routing_rule_repository)],
    user_profile_repo: Annotated[
        UserRoutingProfileRepository, Depends(get_user_routing_profile_repository)
    ],
    user_category_pref_repo: Annotated[
        UserCategoryPreferenceRepository, Depends(get_user_category_pref_repository)
    ],
    user_custom_domain_repo: Annotated[
        UserCustomDomainRepository, Depends(get_user_custom_domain_repository)
    ],
    vpn_profile_repo: Annotated[VPNProfileRepository, Depends(get_vpn_profile_repository)],
    engine: Annotated[RoutingEngine, Depends(get_routing_engine)],
) -> RoutingService:
    return RoutingService(
        category_repo,
        rule_repo,
        user_profile_repo,
        user_category_pref_repo,
        user_custom_domain_repo,
        vpn_profile_repo,
        engine,
    )


def get_subscription_link_service(
    repo: Annotated[SubscriptionLinkRepository, Depends(get_subscription_link_repository)],
) -> SubscriptionLinkService:
    return SubscriptionLinkService(repo)


def get_device_service(
    settings: SettingsDep,
    device_repo: Annotated[DeviceRepository, Depends(get_device_repository)],
    peer_repo: Annotated[VPNPeerRepository, Depends(get_vpn_peer_repository)],
    subscription_repo: Annotated[SubscriptionRepository, Depends(get_subscription_repository)],
    server_service: Annotated[VPNServerService, Depends(get_vpn_server_service)],
    routing_service: Annotated[RoutingService, Depends(get_routing_service)],
    provider: Annotated[VPNProvider, Depends(get_vpn_provider)],
    subscription_link_service: Annotated[
        SubscriptionLinkService, Depends(get_subscription_link_service)
    ],
    vless_credential_repo: Annotated[
        VLESSCredentialRepository, Depends(get_vless_credential_repository)
    ],
    vless_server_config_repo: Annotated[
        VLESSServerConfigRepository, Depends(get_vless_server_config_repository)
    ],
    xray_agent_provider: Annotated[XrayAgentProvider, Depends(get_xray_agent_provider)],
) -> DeviceService:
    return DeviceService(
        device_repo,
        peer_repo,
        subscription_repo,
        server_service,
        routing_service,
        provider,
        subscription_link_service,
        settings.subscription_base_url,
        vless_credential_repo,
        vless_server_config_repo,
        xray_agent_provider,
    )


def get_payment_service(
    settings: SettingsDep,
    payment_repo: Annotated[PaymentRepository, Depends(get_payment_repository)],
    promo_repo: Annotated[PromoCodeRepository, Depends(get_promo_code_repository)],
    promo_redemption_repo: Annotated[
        PromoCodeRedemptionRepository, Depends(get_promo_redemption_repository)
    ],
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
    provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
) -> PaymentService:
    return PaymentService(
        payment_repo,
        promo_repo,
        promo_redemption_repo,
        subscription_service,
        provider,
        settings.payment_provider,
    )


def get_support_service(
    repo: Annotated[SupportTicketRepository, Depends(get_support_ticket_repository)],
    message_repo: Annotated[SupportMessageRepository, Depends(get_support_message_repository)],
) -> SupportService:
    return SupportService(repo, message_repo)


def get_audit_service(
    repo: Annotated[AuditLogRepository, Depends(get_audit_log_repository)],
) -> AuditService:
    return AuditService(repo)


def get_admin_auth_service(
    repo: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
) -> AdminAuthService:
    return AdminAuthService(repo)


def get_referral_service(
    repo: Annotated[ReferralRepository, Depends(get_referral_repository)],
) -> ReferralService:
    return ReferralService(repo)


def get_subscription_formatters() -> dict[str, SubscriptionFormatter]:
    """The entire extension point for future clients (Happ, v2rayNG, ...) — a new format
    is a new entry here, nothing else in the WireGuard delivery path changes. VLESS is
    dispatched separately (see SubscriptionDeliveryService.deliver — a VLESS device
    always renders via VLESSFormatter regardless of this registry, since ?format=
    swapping doesn't make sense across protocols); this registry stays WireGuard-format-
    family only, exactly as before."""
    formatter = WireGuardFormatter()
    return {formatter.format_id: formatter}


def get_vless_formatter() -> VLESSFormatter:
    return VLESSFormatter()


def get_subscription_delivery_service(
    link_service: Annotated[SubscriptionLinkService, Depends(get_subscription_link_service)],
    device_repo: Annotated[DeviceRepository, Depends(get_device_repository)],
    subscription_repo: Annotated[SubscriptionRepository, Depends(get_subscription_repository)],
    peer_repo: Annotated[VPNPeerRepository, Depends(get_vpn_peer_repository)],
    server_repo: Annotated[VPNServerRepository, Depends(get_vpn_server_repository)],
    profile_repo: Annotated[VPNProfileRepository, Depends(get_vpn_profile_repository)],
    formatters: Annotated[dict[str, SubscriptionFormatter], Depends(get_subscription_formatters)],
    vless_credential_repo: Annotated[
        VLESSCredentialRepository, Depends(get_vless_credential_repository)
    ],
    vless_server_config_repo: Annotated[
        VLESSServerConfigRepository, Depends(get_vless_server_config_repository)
    ],
    vless_formatter: Annotated[VLESSFormatter, Depends(get_vless_formatter)],
) -> SubscriptionDeliveryService:
    return SubscriptionDeliveryService(
        link_service,
        device_repo,
        subscription_repo,
        peer_repo,
        server_repo,
        profile_repo,
        formatters,
        vless_credential_repo,
        vless_server_config_repo,
        vless_formatter,
    )


# ---- Auth guards ----


async def require_internal_service(
    settings: SettingsDep,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    """Gate for endpoints only the Telegram bot (a trusted first-party service) may call."""
    if not x_internal_token or not constant_time_compare(
        x_internal_token, settings.internal_service_token
    ):
        raise UnauthorizedError(
            "Invalid internal service token", error_code="invalid_internal_token"
        )


async def get_current_admin(
    settings: SettingsDep,
    admin_repo: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
    authorization: Annotated[str | None, Header()] = None,
) -> AdminUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise UnauthorizedError("Missing bearer token", error_code="missing_token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access" or payload.get("kind") != "admin":
        raise UnauthorizedError("Invalid or expired token", error_code="invalid_token")
    admin = await admin_repo.get(int(payload["sub"]))
    if admin is None or not admin.is_active:
        raise UnauthorizedError("Admin account not found or inactive", error_code="admin_inactive")
    return admin


async def get_current_user(
    _: Annotated[None, Depends(require_internal_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    x_telegram_user_id: Annotated[int | None, Header()] = None,
) -> User:
    """Resolves the acting end-user for bot-facing endpoints. The bot has already
    authenticated the human via Telegram; this only checks that the *caller* (the bot) is
    trusted (`require_internal_service`) and that the referenced user is active."""
    if x_telegram_user_id is None:
        raise UnauthorizedError(
            "Missing X-Telegram-User-Id header", error_code="missing_user_header"
        )
    return await user_service.require_active_user(x_telegram_user_id)


def require_admin_role(*roles: AdminRole) -> Callable:
    async def _check(admin: Annotated[AdminUser, Depends(get_current_admin)]) -> AdminUser:
        if roles and admin.role not in roles:
            raise PermissionDeniedError("Insufficient admin role", error_code="insufficient_role")
        return admin

    return _check
