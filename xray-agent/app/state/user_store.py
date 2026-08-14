"""Tracks which VLESS users *should* exist on this node's Xray inbound.

Xray itself has no durable state: a client either has a live entry on the running
inbound (added via the HandlerService gRPC API — see app/xray/handler_client.py) or it
doesn't, and that entry is lost on every process restart with nothing on disk to
recover it from (unlike WireGuard's wg0.conf + SaveConfig=true). This store is what
lets xray-agent be self-healing — the durable desired state lives here, and
UserReconciler (app/xray/reconciler.py) is what converges Xray's live state to match it,
both at startup and periodically. This store never contains a Reality private key or
anything else beyond the identifiers needed to reconstruct a user on Xray.
"""

import asyncio
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class UserRecord:
    uuid: str
    device_id: int
    email: str
    flow: str
    enabled: bool
    created_at: datetime
    rotated_at: datetime | None


class UserStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # A single long-lived connection: sqlite3.connect(":memory:") would otherwise
        # open a brand-new, empty database on every call, silently discarding all prior
        # writes. asyncio.to_thread may run each call on a different worker thread, so
        # the connection is created with check_same_thread=False and access is
        # serialized via a lock — same pattern as vpn-agent's PeerStore.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    uuid TEXT PRIMARY KEY,
                    device_id INTEGER NOT NULL,
                    email TEXT NOT NULL,
                    flow TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    rotated_at TEXT
                )
                """
            )

    @staticmethod
    def _row_to_record(row: tuple) -> UserRecord:
        return UserRecord(
            uuid=row[0],
            device_id=row[1],
            email=row[2],
            flow=row[3],
            enabled=bool(row[4]),
            created_at=datetime.fromisoformat(row[5]),
            rotated_at=datetime.fromisoformat(row[6]) if row[6] else None,
        )

    _COLUMNS = "uuid, device_id, email, flow, enabled, created_at, rotated_at"

    def _upsert_sync(self, record: UserRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO users ({self._COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    device_id=excluded.device_id,
                    email=excluded.email,
                    flow=excluded.flow,
                    enabled=excluded.enabled
                """,
                (
                    record.uuid,
                    record.device_id,
                    record.email,
                    record.flow,
                    int(record.enabled),
                    record.created_at.isoformat(),
                    record.rotated_at.isoformat() if record.rotated_at else None,
                ),
            )

    def _get_sync(self, uuid: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM users WHERE uuid = ?", (uuid,)
            ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def _delete_sync(self, uuid: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE uuid = ?", (uuid,))

    def _list_enabled_sync(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {self._COLUMNS} FROM users WHERE enabled = 1").fetchall()
        return [self._row_to_record(r) for r in rows]

    def _list_all_sync(self) -> list[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute(f"SELECT {self._COLUMNS} FROM users").fetchall()
        return [self._row_to_record(r) for r in rows]

    async def upsert(
        self,
        *,
        uuid: str,
        device_id: int,
        email: str,
        flow: str,
        rotated_at: datetime | None = None,
    ) -> UserRecord:
        existing = await self.get(uuid)
        if rotated_at is None and existing is not None:
            rotated_at = existing.rotated_at
        record = UserRecord(
            uuid=uuid,
            device_id=device_id,
            email=email,
            flow=flow,
            enabled=True,
            created_at=existing.created_at if existing is not None else datetime.now(UTC),
            rotated_at=rotated_at,
        )
        await asyncio.to_thread(self._upsert_sync, record)
        return record

    async def get(self, uuid: str) -> UserRecord | None:
        return await asyncio.to_thread(self._get_sync, uuid)

    async def delete(self, uuid: str) -> None:
        await asyncio.to_thread(self._delete_sync, uuid)

    async def list_enabled(self) -> list[UserRecord]:
        return await asyncio.to_thread(self._list_enabled_sync)

    async def list_all(self) -> list[UserRecord]:
        return await asyncio.to_thread(self._list_all_sync)
