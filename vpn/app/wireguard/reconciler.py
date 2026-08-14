"""Coordinates the desired peer state (PeerStore) with the live WireGuard interface.

This is the only place that decides *when* to touch the OS interface. In local/dev/test
(`apply_to_live_interface=False`) it tracks state without shelling out, so the rest of the
agent — and its test suite — never needs a real `wg0` interface or root privileges.
"""

from app.core.logging import get_logger
from app.state.peer_store import PeerStore
from app.wireguard.interface import PeerStats, WireGuardInterface

logger = get_logger(__name__)


class PeerReconciler:
    def __init__(
        self, interface: WireGuardInterface, store: PeerStore, apply_to_live_interface: bool
    ) -> None:
        self.interface = interface
        self.store = store
        self._apply = apply_to_live_interface

    async def add_peer(self, *, public_key: str, device_id: int, assigned_ip: str) -> None:
        await self.store.upsert(
            public_key=public_key, device_id=device_id, assigned_ip=assigned_ip, enabled=True
        )
        if self._apply:
            await self.interface.add_or_update_peer(public_key, [assigned_ip])
            await self.interface.save_config()

    async def remove_peer(self, public_key: str) -> None:
        await self.store.delete(public_key)
        if self._apply:
            await self.interface.remove_peer(public_key)
            await self.interface.save_config()

    async def disable_peer(self, public_key: str) -> None:
        await self.store.set_enabled(public_key, False)
        if self._apply:
            # Removing from the live interface (while keeping the DB record) is what makes
            # "disabled" actually stop traffic — WireGuard has no paused state of its own.
            await self.interface.remove_peer(public_key)
            await self.interface.save_config()

    async def enable_peer(self, public_key: str) -> None:
        record = await self.store.get(public_key)
        if record is None:
            return
        await self.store.set_enabled(public_key, True)
        if self._apply:
            await self.interface.add_or_update_peer(public_key, [record.assigned_ip])
            await self.interface.save_config()

    async def set_allowed_ips(self, public_key: str, allowed_ips: list[str]) -> None:
        """Used for Smart VPN AllowedIPs refreshes pushed from the backend. Note this only
        affects the *client's own* tunnel config (rendered by the backend); the server side
        keeps routing that peer by its fixed `assigned_ip` regardless, so this call is a
        no-op against the live interface today and exists for forward-compatibility with a
        future server-side routing mode."""
        record = await self.store.get(public_key)
        if record is None:
            return
        logger.info("peer_allowed_ips_noted", public_key=public_key, count=len(allowed_ips))

    async def get_peer_stats(self, public_key: str) -> PeerStats | None:
        if not self._apply:
            return None
        for stats in await self.interface.dump():
            if stats.public_key == public_key:
                return stats
        return None

    async def reconcile_on_startup(self) -> None:
        """Re-applies every enabled peer to the live interface — makes the agent
        self-healing after a reboot or wg-quick restart without waiting for backend calls."""
        if not self._apply:
            return
        enabled = await self.store.list_enabled()
        for record in enabled:
            await self.interface.add_or_update_peer(record.public_key, [record.assigned_ip])
        logger.info("startup_reconciliation_complete", peer_count=len(enabled))
