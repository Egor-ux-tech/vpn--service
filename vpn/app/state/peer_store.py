"""Tracks which peers *should* exist on this server and whether each is enabled.

WireGuard itself has no notion of a "disabled" peer — a peer either has AllowedIPs (and can
therefore route traffic) or has been removed entirely. To support disable/enable without
losing the peer's assigned IP, the agent keeps its own small durable record and reconciles
the live interface to match it. This store never contains a private key — the agent
generates a keypair once per `create_peer` call, returns the private key in that single
response, and forgets it immediately (see `api/peers.py`).
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
class PeerRecord:
    public_key: str
    device_id: int
    assigned_ip: str
    enabled: bool
    created_at: datetime


class PeerStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # A single long-lived connection: sqlite3.connect(":memory:") would otherwise open a
        # brand-new, empty database on every call, silently discarding all prior writes.
        # asyncio.to_thread may run each call on a different worker thread, so the
        # connection is created with check_same_thread=False and access is serialized.
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
                CREATE TABLE IF NOT EXISTS peers (
                    public_key TEXT PRIMARY KEY,
                    device_id INTEGER NOT NULL,
                    assigned_ip TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _upsert_sync(self, record: PeerRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO peers (public_key, device_id, assigned_ip, enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(public_key) DO UPDATE SET
                    device_id=excluded.device_id,
                    assigned_ip=excluded.assigned_ip,
                    enabled=excluded.enabled
                """,
                (
                    record.public_key,
                    record.device_id,
                    record.assigned_ip,
                    int(record.enabled),
                    record.created_at.isoformat(),
                ),
            )

    def _get_sync(self, public_key: str) -> PeerRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT public_key, device_id, assigned_ip, enabled, created_at "
                "FROM peers WHERE public_key = ?",
                (public_key,),
            ).fetchone()
        if row is None:
            return None
        return PeerRecord(
            public_key=row[0],
            device_id=row[1],
            assigned_ip=row[2],
            enabled=bool(row[3]),
            created_at=datetime.fromisoformat(row[4]),
        )

    def _set_enabled_sync(self, public_key: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE peers SET enabled = ? WHERE public_key = ?", (int(enabled), public_key)
            )

    def _delete_sync(self, public_key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM peers WHERE public_key = ?", (public_key,))

    def _list_enabled_sync(self) -> list[PeerRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT public_key, device_id, assigned_ip, enabled, created_at "
                "FROM peers WHERE enabled = 1"
            ).fetchall()
        return [
            PeerRecord(
                public_key=r[0],
                device_id=r[1],
                assigned_ip=r[2],
                enabled=bool(r[3]),
                created_at=datetime.fromisoformat(r[4]),
            )
            for r in rows
        ]

    async def upsert(
        self, *, public_key: str, device_id: int, assigned_ip: str, enabled: bool = True
    ) -> PeerRecord:
        record = PeerRecord(
            public_key=public_key,
            device_id=device_id,
            assigned_ip=assigned_ip,
            enabled=enabled,
            created_at=datetime.now(UTC),
        )
        await asyncio.to_thread(self._upsert_sync, record)
        return record

    async def get(self, public_key: str) -> PeerRecord | None:
        return await asyncio.to_thread(self._get_sync, public_key)

    async def set_enabled(self, public_key: str, enabled: bool) -> None:
        await asyncio.to_thread(self._set_enabled_sync, public_key, enabled)

    async def delete(self, public_key: str) -> None:
        await asyncio.to_thread(self._delete_sync, public_key)

    async def list_enabled(self) -> list[PeerRecord]:
        return await asyncio.to_thread(self._list_enabled_sync)
