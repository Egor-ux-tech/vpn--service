"""Orchestrates GET /sub/{token}: resolve -> re-authorize everything from scratch -> pick a
formatter -> render. Every failure mode — bad token, revoked link, lapsed billing
subscription, disabled/revoked device, peer not usable — raises the exact same
NotFoundError, deliberately. This endpoint is reachable by anyone who has (or is guessing)
a token, with no other identity behind the request, so it must never let a response shape,
status code, or timing difference tell an attacker *why* a guess failed — see
docs/subscription-delivery.md's security section.
"""

from datetime import UTC, datetime

from app.core.errors import NotFoundError
from app.models.device import Device
from app.models.enums import DeviceStatus, SubscriptionLinkStatus, VPNPeerStatus, VPNProtocol
from app.repositories.device_repository import DeviceRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vless_credential_repository import VLESSCredentialRepository
from app.repositories.vless_server_config_repository import VLESSServerConfigRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.repositories.vpn_profile_repository import VPNProfileRepository
from app.repositories.vpn_server_repository import VPNServerRepository
from app.services.subscription_delivery.formatters.base import SubscriptionFormatter
from app.services.subscription_delivery.formatters.vless_formatter import VLESSFormatter
from app.services.subscription_link_service import SubscriptionLinkService

_GENERIC_NOT_FOUND = "Not found"


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite (unlike Postgres) has no native tz-aware timestamp type: a `DateTime
    (timezone=True)` column round-trips correctly within the *same* session/object, but a
    fresh read in a new session comes back naive — confirmed empirically, not
    theoretical (this comparison crashed with "can't compare offset-naive and
    offset-aware datetimes" against exactly that scenario). Every timestamp this codebase
    writes is UTC (see SubscriptionService.activate, etc.), so a naive value is always
    safe to treat as UTC rather than a genuine ambiguity to reject."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SubscriptionDeliveryService:
    def __init__(
        self,
        link_service: SubscriptionLinkService,
        device_repository: DeviceRepository,
        subscription_repository: SubscriptionRepository,
        peer_repository: VPNPeerRepository,
        server_repository: VPNServerRepository,
        profile_repository: VPNProfileRepository,
        formatters: dict[str, SubscriptionFormatter],
        vless_credential_repository: VLESSCredentialRepository,
        vless_server_config_repository: VLESSServerConfigRepository,
        vless_formatter: VLESSFormatter,
        default_format: str = "wireguard",
    ) -> None:
        self._links = link_service
        self._devices = device_repository
        self._subscriptions = subscription_repository
        self._peers = peer_repository
        self._servers = server_repository
        self._profiles = profile_repository
        self._formatters = formatters
        self._vless_credentials = vless_credential_repository
        self._vless_server_configs = vless_server_config_repository
        self._vless_formatter = vless_formatter
        self._default_format = default_format

    async def deliver(self, token: str, *, format_hint: str | None = None) -> tuple[bytes, str]:
        device = await self._authorize(token)

        if device.protocol is VPNProtocol.VLESS:
            return await self._deliver_vless(device)

        peer = await self._peers.get_active_for_device(device.id)
        if peer is None or peer.status != VPNPeerStatus.ACTIVE:
            raise NotFoundError(_GENERIC_NOT_FOUND, error_code="not_found")

        server = await self._servers.get(peer.server_id)
        if server is None:
            raise NotFoundError(_GENERIC_NOT_FOUND, error_code="not_found")

        profile = await self._profiles.get_current_for_device(device.id)

        # Unknown/omitted format falls back to the default rather than erroring — a typo'd
        # ?format= shouldn't turn into a failure mode indistinguishable from "bad token"
        # (which would leak that the token itself was fine), and there's nothing sensitive
        # about which formatter renders the response.
        formatter = self._formatters.get(format_hint) if format_hint else None
        if formatter is None:
            formatter = self._formatters[self._default_format]
        content = await formatter.render(device=device, peer=peer, server=server, profile=profile)
        return content, formatter.content_type

    async def _deliver_vless(self, device: Device) -> tuple[bytes, str]:
        # format_hint is deliberately ignored for VLESS devices — there is only one
        # renderer for this protocol today (no WireGuard-style format registry lookup),
        # and honoring an unrelated ?format= here would be a confusing, meaningless
        # no-op rather than a real feature — see VLESSFormatter's docstring.
        credentials = await self._vless_credentials.list_active_for_device(device.id)
        items = []
        for credential in credentials:
            server = await self._servers.get(credential.server_id)
            if server is None:
                continue
            server_config = await self._vless_server_configs.get_for_server(server.id)
            if server_config is None:
                continue
            items.append((credential, server, server_config))

        if not items:
            raise NotFoundError(_GENERIC_NOT_FOUND, error_code="not_found")

        content = await self._vless_formatter.render(device=device, items=items)
        return content, self._vless_formatter.content_type

    async def _authorize(self, token: str) -> Device:
        """Every one of these checks must fail the exact same way (see module docstring).
        Order is chosen for cost, not for information value to a caller — cheapest checks
        first — since none of them are ever allowed to be distinguishable from outside."""
        link = await self._links.resolve_token(token)
        if link is None or link.status != SubscriptionLinkStatus.ACTIVE:
            raise NotFoundError(_GENERIC_NOT_FOUND, error_code="not_found")

        device = await self._devices.get(link.device_id)
        if device is None or device.status != DeviceStatus.ACTIVE:
            raise NotFoundError(_GENERIC_NOT_FOUND, error_code="not_found")

        subscription = await self._subscriptions.get_active_for_user(device.user_id)
        now = datetime.now(UTC)
        if (
            subscription is None
            or subscription.expires_at is None
            or _as_aware_utc(subscription.expires_at) <= now
        ):
            raise NotFoundError(_GENERIC_NOT_FOUND, error_code="not_found")

        await self._links.record_access(link)
        return device
