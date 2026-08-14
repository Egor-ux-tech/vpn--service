import uuid as uuid_lib
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
from app.models.enums import DeviceStatus, VLESSCredentialStatus, VPNPeerStatus, VPNProtocol
from app.models.user import User
from app.models.vless_credential import VLESSCredential
from app.models.vless_server_config import VLESSServerConfig
from app.models.vpn_peer import VPNPeer
from app.models.vpn_server import VPNServer
from app.repositories.device_repository import DeviceRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vless_credential_repository import VLESSCredentialRepository
from app.repositories.vless_server_config_repository import VLESSServerConfigRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
from app.services.routing_service import RoutingService
from app.services.subscription_link_service import SubscriptionLinkService, build_subscription_url
from app.services.vless.provider import XrayAgentProvider
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
    # A downloadable, immediately-usable config file + its QR — only meaningful for
    # WireGuard (where the private key is returned once and must be delivered right
    # away). None for VLESS devices: there is no separate per-provisioning artifact,
    # since the subscription link (below) *is* the config — GET /sub/{token} always
    # returns the device's current vless:// line(s), live, not a one-time push.
    config_text: str | None
    qr_code_base64: str | None
    # Only set by provision() — reissue() rotates the WireGuard keypair, not the
    # subscription link, and the link's plaintext token is never available again after
    # creation (only its hash is stored — see SubscriptionLinkService), so there is no
    # value reissue() could put here even if it wanted to.
    subscription_url: str | None = None
    subscription_qr_code_base64: str | None = None


class DeviceService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        peer_repository: VPNPeerRepository,
        subscription_repository: SubscriptionRepository,
        server_service: VPNServerService,
        routing_service: RoutingService,
        provider: VPNProvider,
        subscription_link_service: SubscriptionLinkService,
        subscription_base_url: str,
        vless_credential_repository: VLESSCredentialRepository,
        vless_server_config_repository: VLESSServerConfigRepository,
        xray_agent_provider: XrayAgentProvider,
    ) -> None:
        self._devices = device_repository
        self._peers = peer_repository
        self._subscriptions = subscription_repository
        self._server_service = server_service
        self._routing_service = routing_service
        self._provider = provider
        self._subscription_links = subscription_link_service
        self._subscription_base_url = subscription_base_url
        self._vless_credentials = vless_credential_repository
        self._vless_server_configs = vless_server_config_repository
        self._xray_agent_provider = xray_agent_provider

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
        self,
        *,
        user: User,
        name: str,
        requested_server_id: int | None = None,
        protocol: VPNProtocol = VPNProtocol.WIREGUARD,
    ) -> ProvisionedDevice:
        await self._enforce_device_limit(user)

        if protocol is VPNProtocol.VLESS:
            return await self._provision_vless(
                user=user, name=name, requested_server_id=requested_server_id
            )

        server = (
            await self._server_service.get(requested_server_id)
            if requested_server_id
            else await self._server_service.pick_best_available(VPNProtocol.WIREGUARD)
        )

        device = Device(user_id=user.id, name=name, status=DeviceStatus.ACTIVE)
        self._devices.add(device)
        await self._devices.flush()

        # Every device gets a subscription link automatically — it only needs device.id,
        # so this can happen before the peer/routing work below. create_or_rotate is safe
        # to call here unconditionally: this device.id is guaranteed brand new, so there is
        # never an existing link to rotate, only ever a fresh create.
        _, subscription_token = await self._subscription_links.create_or_rotate(device)
        subscription_url = build_subscription_url(self._subscription_base_url, subscription_token)

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
        subscription_qr_code = generate_qr_code_base64(subscription_url)

        return ProvisionedDevice(
            device=device,
            config_text=config_text,
            qr_code_base64=qr_code,
            subscription_url=subscription_url,
            subscription_qr_code_base64=subscription_qr_code,
        )

    async def _provision_vless(
        self, *, user: User, name: str, requested_server_id: int | None = None
    ) -> ProvisionedDevice:
        """No IP allocation, no keypair, no VPNPeer — see app/models/vless_credential.py
        for why VLESS credentials are a separate model. Mirrors provision()'s WireGuard
        flow structurally (limit check already done by the caller, device row first so
        the subscription link can attach to it, then the transport-specific identity)."""
        server = (
            await self._server_service.get(requested_server_id)
            if requested_server_id
            else await self._server_service.pick_best_available(VPNProtocol.VLESS)
        )
        server_config = await self._vless_server_configs.get_for_server(server.id)
        if server_config is None:
            raise ConflictError(
                f"VLESS server {server.id} has no Reality configuration",
                error_code="vless_server_not_configured",
            )

        device = Device(
            user_id=user.id,
            name=name,
            status=DeviceStatus.ACTIVE,
            protocol=VPNProtocol.VLESS,
            server_id=server.id,
        )
        self._devices.add(device)
        await self._devices.flush()

        _, subscription_token = await self._subscription_links.create_or_rotate(device)
        subscription_url = build_subscription_url(self._subscription_base_url, subscription_token)

        # UUID identity is generated here, by the backend — never by xray-agent (see
        # docs/xray-agent.md) — matching this codebase's existing IP-allocation
        # ownership principle (allocate_ip is a control-plane responsibility, not the
        # agent's) applied to VLESS's equivalent identity primitive.
        new_uuid = str(uuid_lib.uuid4())
        user_record = await self._xray_agent_provider.create_user(
            server_config=server_config, uuid=new_uuid, device_id=device.id, flow=server_config.flow
        )
        credential = VLESSCredential(
            device_id=device.id,
            server_id=server.id,
            uuid=user_record.uuid,
            status=VLESSCredentialStatus.ACTIVE,
        )
        self._vless_credentials.add(credential)
        await self._vless_credentials.flush()

        server.current_load += 1

        subscription_qr_code = generate_qr_code_base64(subscription_url)
        return ProvisionedDevice(
            device=device,
            config_text=None,
            qr_code_base64=None,
            subscription_url=subscription_url,
            subscription_qr_code_base64=subscription_qr_code,
        )

    async def _vless_server_config_for_credential(
        self, credential: VLESSCredential
    ) -> tuple[VPNServer, VLESSServerConfig] | None:
        server = await self._server_service.get(credential.server_id)
        server_config = await self._vless_server_configs.get_for_server(server.id)
        if server_config is None:
            return None
        return server, server_config

    async def _remove_vless_credential_from_xray(self, credential: VLESSCredential) -> None:
        found = await self._vless_server_config_for_credential(credential)
        if found is None:
            return
        _, server_config = found
        await self._xray_agent_provider.remove_user(
            server_config=server_config, uuid=credential.uuid
        )

    async def _revoke_vless_credentials(self, device: Device) -> None:
        for credential in await self._vless_credentials.list_active_for_device(device.id):
            await self._remove_vless_credential_from_xray(credential)
            credential.status = VLESSCredentialStatus.REVOKED
            credential.revoked_at = datetime.now(UTC)
            server = await self._server_service.get(credential.server_id)
            server.current_load = max(0, server.current_load - 1)

    async def _disable_vless_credentials(self, device: Device) -> None:
        for credential in await self._vless_credentials.list_active_for_device(device.id):
            await self._remove_vless_credential_from_xray(credential)
            credential.status = VLESSCredentialStatus.DISABLED

    async def _enable_vless_credentials(self, device: Device) -> None:
        all_credentials = await self._vless_credentials.list_for_device(device.id)
        for credential in all_credentials:
            if credential.status != VLESSCredentialStatus.DISABLED:
                continue
            found = await self._vless_server_config_for_credential(credential)
            if found is None:
                continue
            _, server_config = found
            # Idempotent re-add with the SAME uuid — no rotation, no new identity;
            # disable/enable is meant to be reversible without invalidating the
            # subscription content the user already has (see xray-agent's POST /users).
            await self._xray_agent_provider.create_user(
                server_config=server_config,
                uuid=credential.uuid,
                device_id=device.id,
                flow=server_config.flow,
            )
            credential.status = VLESSCredentialStatus.ACTIVE

    async def reissue(self, *, device: Device) -> ProvisionedDevice:
        """Rotates credentials: the old peer is revoked and a brand-new keypair is
        provisioned, since the backend never retains a private key to resend."""
        if device.protocol is VPNProtocol.VLESS:
            raise ValidationAppError(
                "Reissue is not supported for VLESS devices — the subscription link "
                "always reflects the device's current credential live; rotate the "
                "subscription link instead if a fresh URL is needed",
                error_code="reissue_not_supported_for_protocol",
            )
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
        if device.protocol is VPNProtocol.VLESS:
            await self._revoke_vless_credentials(device)
        elif device.server_id is not None:
            server = await self._server_service.get(device.server_id)
            peer = await self._peers.get_active_for_device(device.id)
            if peer is not None:
                await self._provider.delete_peer(peer=peer, server=server)
                peer.status = VPNPeerStatus.REVOKED
                server.current_load = max(0, server.current_load - 1)
        device.status = DeviceStatus.REVOKED
        return device

    async def disable(self, *, device: Device) -> Device:
        if device.protocol is VPNProtocol.VLESS:
            await self._disable_vless_credentials(device)
        else:
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
        if device.protocol is VPNProtocol.VLESS:
            await self._enable_vless_credentials(device)
        else:
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
