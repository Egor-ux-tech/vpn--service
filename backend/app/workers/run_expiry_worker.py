"""Cron/systemd-timer entrypoint: `python -m app.workers.run_expiry_worker`.

Wires the same services the API uses but with a hand-built session and dependency graph
(no FastAPI request scope exists here) — see docs/deployment.md for the systemd timer unit.
"""

import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import AsyncSessionLocal
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.routing_repository import (
    RoutingCategoryRepository,
    RoutingRuleRepository,
    UserCategoryPreferenceRepository,
    UserCustomDomainRepository,
    UserRoutingProfileRepository,
)
from app.repositories.subscription_link_repository import SubscriptionLinkRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vless_credential_repository import VLESSCredentialRepository
from app.repositories.vless_server_config_repository import VLESSServerConfigRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.repositories.vpn_server_repository import VPNServerRepository
from app.services.audit_service import AuditService
from app.services.device_service import DeviceService
from app.services.notifications.bot_notifier import BotNotifier
from app.services.routing.dns_resolver import DomainResolver
from app.services.routing.engine import RoutingEngine
from app.services.routing_service import RoutingService
from app.services.subscription_link_service import SubscriptionLinkService
from app.services.subscription_service import SubscriptionService
from app.services.vless.xray_agent_provider import HttpXrayAgentProvider
from app.services.vpn.wireguard_provider import WireGuardProvider
from app.services.vpn_server_service import VPNServerService
from app.workers.subscription_expiry import SubscriptionExpiryWorker

logger = get_logger(__name__)


async def run() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    async with AsyncSessionLocal() as session:
        routing_service = RoutingService(
            RoutingCategoryRepository(session),
            RoutingRuleRepository(session),
            UserRoutingProfileRepository(session),
            UserCategoryPreferenceRepository(session),
            UserCustomDomainRepository(session),
            VPNProfileRepository(session),
            RoutingEngine(DomainResolver(nameservers=settings.vpn_dns_list)),
        )
        device_service = DeviceService(
            DeviceRepository(session),
            VPNPeerRepository(session),
            SubscriptionRepository(session),
            VPNServerService(VPNServerRepository(session)),
            routing_service,
            WireGuardProvider(
                shared_secret=settings.vpn_agent_shared_secret, dns_servers=settings.vpn_dns_list
            ),
            SubscriptionLinkService(SubscriptionLinkRepository(session)),
            settings.subscription_base_url,
            VLESSCredentialRepository(session),
            VLESSServerConfigRepository(session),
            HttpXrayAgentProvider(shared_secret=settings.xray_agent_shared_secret),
        )
        worker = SubscriptionExpiryWorker(
            subscription_service=SubscriptionService(SubscriptionRepository(session)),
            device_service=device_service,
            audit_service=AuditService(AuditLogRepository(session)),
            notifier=BotNotifier(
                bot_notify_base_url=settings.bot_notify_base_url,
                internal_service_token=settings.internal_service_token,
            ),
        )

        summary = await worker.run_once()
        await session.commit()

    logger.info("expiry_worker_finished", expired_count=summary.count)
    return summary.count


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
