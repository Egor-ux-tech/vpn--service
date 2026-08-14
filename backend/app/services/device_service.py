from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    ConflictError,
    LimitExceededError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
)
from app.models.device import Device
from app.models.enums import DeviceStatus, VPNPeerStatus
from app.models.user import User
from app.models.vpn_peer import VPNPeer
from app.models.vpn_server import VPNServer
from app.repositories.device_repository import DeviceRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.services.routing_service import RoutingService
from app.services.vpn.ip_allocator import allocate_ip
from app.services.vpn.provider import PeerProvisioningResult, VPNProvider
from app.services.vpn.qrcode_util import generate_qr_code_base64
from app.services.vpn_server_service import VPNServerService

DEFAULT_FREE_DEVICE_LIMIT = 1

# Concurrent requests can both compute the same "free" IP from allocate_ip's own read (a
# plain SELECT, not locked) before either has committed — the DB's unique constraint on
# (server_id, assigned_ip) is the actual arbiter. This bounds how many times we retry with
# a freshly rescanned IP before giving up and surfacing a clear error, rather than retrying
# forever under sustained contention.
_MAX_IP_ALLOCATION_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class ProvisionedDevice:
    device: Device
    config_text: str
    qr_code_base64: str


class DeviceService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        peer_repository: VPNPeerRepository,
        subscription_repository: SubscriptionRepository,
        server_service: VPNServerService,
        routing_service: RoutingService,
        provider: VPNProvider,
    ) -> None:
        self._devices = device_repository
        self._peers = peer_repository
        self._subscriptions = subscription_repository
        self._server_service = server_service
        self._routing_service = routing_service
        self._provider = provider

    async def _enforce_device_limit(self, user: User) -> None:
        subscription = await self._subscriptions.get_active_for_user(user.id)
        if subscription is None:
            raise PermissionDeniedError(
                "An active subscription is required to add a device",
                error_code="no_active_subscription",
            )
        limit = subscription.device_limit_override or subscription.plan.max_devices
        active_count = await self._devices.count_active_for_user(user.id)
        if active_count >= limit:
            raise LimitExceededError(
                f"Device limit reached ({active_count}/{limit}) for the current plan",
                error_code="device_limit_reached",
            )

    async def list_for_user(self, user_id: int) -> list[Device]:
        return await self._devices.list_for_user(user_id)

    async def get_owned(self, device_id: int, user_id: int) -> Device:
        device = await self._devices.get(device_id)
        if device is None or device.user_id != user_id:
            raise NotFoundError("Device not found", error_code="device_not_found")
        return device

    async def _create_peer_with_retry(
        self, *, device: Device, server: VPNServer
    ) -> tuple[PeerProvisioningResult, VPNPeer]:
        """Allocates an IP and persists the peer row, retrying on a lost allocation race.

        Each attempt: pick a candidate free IP, provision it on the real vpn-agent (which
        generates the keypair), then try to persist the peer row inside a SAVEPOINT. If a
        concurrent request already took that IP, the unique constraint on
        (server_id, assigned_ip) turns the flush into an IntegrityError, the SAVEPOINT rolls
        back just that insert (the surrounding transaction — e.g. the already-created Device
        row — is untouched), and the agent-side peer we just created for the losing IP is
        deleted before retrying with a freshly rescanned candidate. This never leaves an
        orphaned peer on the vpn-agent for an IP nobody ended up owning.
        """
        last_error: Exception | None = None
        for _ in range(_MAX_IP_ALLOCATION_ATTEMPTS):
            assigned_ip = await allocate_ip(
                peer_repository=self._peers,
                server_id=server.id,
                network_cidr=server.internal_network,
            )
            result = await self._provider.create_peer(
                device=device, server=server, assigned_ip=assigned_ip
            )
            peer = VPNPeer(
                device_id=device.id,
                server_id=server.id,
                public_key=result.public_key,
                assigned_ip=result.assigned_ip,
                status=VPNPeerStatus.ACTIVE,
            )
            try:
                async with self._peers.session.begin_nested():
                    self._peers.add(peer)
                    await self._peers.flush()
            except IntegrityError as exc:
                last_error = exc
                await self._provider.delete_peer(peer=peer, server=server)
                continue
            return result, peer

        raise ConflictError(
            f"Could not allocate a free IP on server {server.id} after "
            f"{_MAX_IP_ALLOCATION_ATTEMPTS} attempts due to concurrent provisioning",
            error_code="ip_allocation_conflict",
        ) from last_error

    async def provision(
        self, *, user: User, name: str, requested_server_id: int | None = None
    ) -> ProvisionedDevice:
        await self._enforce_device_limit(user)

        server = (
            await self._server_service.get(requested_server_id)
            if requested_server_id
            else await self._server_service.pick_best_available()
        )

        device = Device(user_id=user.id, name=name, status=DeviceStatus.ACTIVE)
        self._devices.add(device)
        await self._devices.flush()

        result, peer = await self._create_peer_with_retry(device=device, server=server)

        device.public_key = peer.public_key
        device.assigned_ip = peer.assigned_ip
        device.server_id = server.id
        server.current_load += 1

        profile = await self._routing_service.regenerate_profile(device, user.id)

        config_text = self._provider.build_client_config(
            private_key=result.private_key,
            assigned_ip=result.assigned_ip,
            server_public_key=result.server_public_key,
            server_endpoint=result.server_endpoint,
            allowed_ips=profile.allowed_ips,
            dns=profile.dns,
        )
        qr_code = generate_qr_code_base64(config_text)

        return ProvisionedDevice(device=device, config_text=config_text, qr_code_base64=qr_code)

    async def reissue(self, *, device: Device) -> ProvisionedDevice:
        """Rotates credentials: the old peer is revoked and a brand-new keypair is
        provisioned, since the backend never retains a private key to resend."""
        if device.server_id is None:
            raise ValidationAppError(
                "Device has no assigned server", error_code="device_not_provisioned"
            )
        server = await self._server_service.get(device.server_id)

        old_peer = await self._peers.get_active_for_device(device.id)
        if old_peer is not None:
            await self._provider.delete_peer(peer=old_peer, server=server)
            old_peer.status = VPNPeerStatus.REVOKED

        result, new_peer = await self._create_peer_with_retry(device=device, server=server)

        device.public_key = new_peer.public_key
        device.assigned_ip = new_peer.assigned_ip

        profile = await self._routing_service.regenerate_profile(device, device.user_id)
        config_text = self._provider.build_client_config(
            private_key=result.private_key,
            assigned_ip=result.assigned_ip,
            server_public_key=result.server_public_key,
            server_endpoint=result.server_endpoint,
            allowed_ips=profile.allowed_ips,
            dns=profile.dns,
        )
        qr_code = generate_qr_code_base64(config_text)
        return ProvisionedDevice(device=device, config_text=config_text, qr_code_base64=qr_code)

    async def revoke(self, *, device: Device) -> Device:
        if device.server_id is not None:
            server = await self._server_service.get(device.server_id)
            peer = await self._peers.get_active_for_device(device.id)
            if peer is not None:
                await self._provider.delete_peer(peer=peer, server=server)
                peer.status = VPNPeerStatus.REVOKED
                server.current_load = max(0, server.current_load - 1)
        device.status = DeviceStatus.REVOKED
        return device

    async def disable(self, *, device: Device) -> Device:
        if device.server_id is None:
            raise ValidationAppError(
                "Device has no assigned server", error_code="device_not_provisioned"
            )
        server = await self._server_service.get(device.server_id)
        peer = await self._peers.get_active_for_device(device.id)
        if peer is not None:
            await self._provider.disable_peer(peer=peer, server=server)
        device.status = DeviceStatus.DISABLED
        return device

    async def enable(self, *, device: Device) -> Device:
        if device.server_id is None:
            raise ValidationAppError(
                "Device has no assigned server", error_code="device_not_provisioned"
            )
        server = await self._server_service.get(device.server_id)
        peer = await self._peers.get_active_for_device(device.id)
        if peer is not None:
            await self._provider.enable_peer(peer=peer, server=server)
        device.status = DeviceStatus.ACTIVE
        return device

    async def touch_last_seen(self, device: Device) -> None:
        device.last_seen = datetime.now(UTC)

    async def disable_all_for_user(self, user_id: int) -> None:
        """Used on subscription expiry — disables VPN access without deleting devices, so
        a renewed subscription can re-enable the same peers instead of re-provisioning."""
        for device in await self._devices.list_for_user(user_id):
            if device.status is DeviceStatus.ACTIVE:
                await self.disable(device=device)
