from datetime import UTC, datetime

from app.core.security import (
    generate_subscription_token,
    hash_subscription_token,
    subscription_token_prefix,
)
from app.models.device import Device
from app.models.enums import SubscriptionLinkStatus
from app.models.subscription_link import SubscriptionLink
from app.repositories.subscription_link_repository import SubscriptionLinkRepository


def build_subscription_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/sub/{token}"


class SubscriptionLinkService:
    """Owns the token lifecycle only — create/rotate/revoke/resolve. Authorization (is the
    underlying device/subscription actually allowed to fetch config right now) lives in
    SubscriptionDeliveryService, which is a distinct concern: a link can be perfectly valid
    as a *token* while the billing subscription behind it has lapsed."""

    def __init__(self, link_repository: SubscriptionLinkRepository) -> None:
        self._links = link_repository

    async def get_for_device(self, device_id: int) -> SubscriptionLink | None:
        return await self._links.get_for_device(device_id)

    async def create_or_rotate(self, device: Device) -> tuple[SubscriptionLink, str]:
        """Idempotent: creates a link if the device has none yet (the normal path, called
        automatically at provisioning — see DeviceService.provision), or rotates the
        existing one to a fresh token otherwise (the user-initiated "regenerate my link"
        path — same endpoint serves both, see api/v1/subscription_links.py).

        Returns the plaintext token alongside the row — this is the *only* place that ever
        exists; only its hash is persisted, so it can never be recovered or re-shown later.
        """
        token = generate_subscription_token()
        token_hash = hash_subscription_token(token)
        token_prefix = subscription_token_prefix(token)

        link = await self._links.get_for_device(device.id)
        if link is None:
            link = SubscriptionLink(
                device_id=device.id,
                token_hash=token_hash,
                token_prefix=token_prefix,
                status=SubscriptionLinkStatus.ACTIVE,
            )
            self._links.add(link)
        else:
            link.token_hash = token_hash
            link.token_prefix = token_prefix
            link.status = SubscriptionLinkStatus.ACTIVE
            link.rotated_at = datetime.now(UTC)
            link.revoked_at = None

        await self._links.flush()
        return link, token

    async def revoke(self, link: SubscriptionLink) -> SubscriptionLink:
        link.status = SubscriptionLinkStatus.REVOKED
        link.revoked_at = datetime.now(UTC)
        return link

    async def resolve_token(self, token: str) -> SubscriptionLink | None:
        """Hash-then-lookup — see core/security.py's comment on why this is the correct,
        constant-time-safe way to verify a high-entropy bearer token (not bcrypt, not a
        raw string comparison)."""
        if not token:
            return None
        return await self._links.get_by_token_hash(hash_subscription_token(token))

    async def record_access(self, link: SubscriptionLink) -> None:
        link.last_accessed_at = datetime.now(UTC)
        link.access_count += 1
