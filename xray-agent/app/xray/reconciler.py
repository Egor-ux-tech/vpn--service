"""Coordinates desired VLESS user state (UserStore) with Xray's live inbound state
(XrayHandlerClient).

Unlike vpn-agent's PeerReconciler — which only reconciles on its own startup, because
WireGuard peers persist across a wg0 restart independently of the agent via
`SaveConfig=true` — this reconciler must also run periodically. Xray-core has no
equivalent durable state: a bare Xray process restart (crash, OOM, manual bounce) wipes
its in-memory user list back to the statically-templated config's empty `clients: []`,
with no local side channel repopulating it. A silent Xray crash-and-respawn (systemd's
`Restart=on-failure` brings the process back, but empty) would otherwise leave every
VLESS user disconnected until this agent happened to restart too — periodic
reconciliation (see main.py's background loop) is what closes that gap. Reconciliation
is bidirectional: missing desired users are re-added (self-healing), and live users no
longer in the desired state are removed (so a revoked/expired credential actually stops
working even if the removal call that should have done so was lost — e.g. this agent
was down when the backend tried to call DELETE /users/{uuid}).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.logging import get_logger
from app.core.metrics import RECONCILIATION_DRIFT_TOTAL, RECONCILIATION_RUNS_TOTAL
from app.state.user_store import UserRecord, UserStore
from app.xray.handler_client import XrayHandlerClient

logger = get_logger(__name__)


@dataclass(slots=True)
class ReconciliationResult:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


class UserReconciler:
    def __init__(
        self,
        handler_client: XrayHandlerClient,
        store: UserStore,
        tag: str,
        apply_to_live: bool,
    ) -> None:
        self.handler_client = handler_client
        self.store = store
        self._tag = tag
        self.apply_to_live = apply_to_live
        self.last_reconciliation_at: datetime | None = None

    async def add_user(self, *, uuid: str, device_id: int, flow: str) -> UserRecord:
        email = _email_for_device(device_id)
        record = await self.store.upsert(uuid=uuid, device_id=device_id, email=email, flow=flow)
        if self.apply_to_live:
            live_emails = await self.handler_client.list_user_emails(tag=self._tag)
            if email not in live_emails:
                await self.handler_client.add_user(tag=self._tag, uuid=uuid, email=email, flow=flow)
        return record

    async def remove_user(self, uuid: str) -> None:
        record = await self.store.get(uuid)
        if record is None:
            return
        if self.apply_to_live:
            await self.handler_client.remove_user(tag=self._tag, email=record.email)
        await self.store.delete(uuid)

    async def rotate_user(self, *, uuid: str, new_uuid: str) -> UserRecord | None:
        old = await self.store.get(uuid)
        if old is None:
            return None
        if self.apply_to_live:
            await self.handler_client.remove_user(tag=self._tag, email=old.email)
        await self.store.delete(uuid)

        new_record = await self.store.upsert(
            uuid=new_uuid,
            device_id=old.device_id,
            email=old.email,
            flow=old.flow,
            rotated_at=datetime.now(UTC),
        )
        if self.apply_to_live:
            await self.handler_client.add_user(
                tag=self._tag, uuid=new_uuid, email=old.email, flow=old.flow
            )
        return new_record

    async def list_users(self) -> list[UserRecord]:
        return await self.store.list_all()

    async def count_live_users(self) -> int:
        return await self.handler_client.count_users(tag=self._tag)

    async def reconcile(self, *, trigger: str) -> ReconciliationResult:
        result = ReconciliationResult()
        RECONCILIATION_RUNS_TOTAL.labels(trigger=trigger).inc()
        if not self.apply_to_live:
            self.last_reconciliation_at = datetime.now(UTC)
            return result

        desired = await self.store.list_enabled()
        desired_by_email = {record.email: record for record in desired}
        live_emails = set(await self.handler_client.list_user_emails(tag=self._tag))

        for email, record in desired_by_email.items():
            if email in live_emails:
                continue
            await self.handler_client.add_user(
                tag=self._tag, uuid=record.uuid, email=email, flow=record.flow
            )
            result.added.append(email)
            RECONCILIATION_DRIFT_TOTAL.labels(action="add").inc()

        for email in live_emails - desired_by_email.keys():
            await self.handler_client.remove_user(tag=self._tag, email=email)
            result.removed.append(email)
            RECONCILIATION_DRIFT_TOTAL.labels(action="remove").inc()

        self.last_reconciliation_at = datetime.now(UTC)
        if result.added or result.removed:
            logger.info(
                "reconciliation_drift_corrected",
                trigger=trigger,
                added_count=len(result.added),
                removed_count=len(result.removed),
            )
        return result


def _email_for_device(device_id: int) -> str:
    """Deterministic, non-secret identity key Xray uses for a user (RemoveUserOperation
    matches by email, not UUID — see docs/xray-agent.md). Never embeds the UUID: the
    UUID is the bearer credential (see app/core/logging.py's redaction list) and must
    never end up inside a differently-named field that redaction-by-key-name would miss."""
    return f"device-{device_id}"
