"""Thin wrapper around the `wg` CLI to reconcile a single WireGuard interface.

Every mutating call here is intentionally narrow (one peer, one field) so the blast radius
of a bug is a single peer, not the whole interface. All commands are run through an
injectable `CommandRunner` so this module is fully unit-testable without root privileges,
the `wireguard-tools` package, or a real network interface.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.metrics import WG_COMMAND_ERRORS_TOTAL


class CommandRunner(Protocol):
    async def __call__(self, *args: str) -> tuple[int, str, str]:
        """Runs a command, returning (returncode, stdout, stderr)."""
        ...


async def subprocess_runner(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


class WireGuardCommandError(RuntimeError):
    def __init__(self, args: tuple[str, ...], returncode: int, stderr: str) -> None:
        # Never interpolate key material into the message — args may contain a public key,
        # which is not secret, but never a private key (this module never receives one).
        super().__init__(f"command {args[0]} failed (code {returncode}): {stderr.strip()}")
        self.returncode = returncode


@dataclass(frozen=True, slots=True)
class PeerStats:
    public_key: str
    endpoint: str | None
    allowed_ips: list[str]
    latest_handshake: datetime | None
    rx_bytes: int
    tx_bytes: int


class WireGuardInterface:
    def __init__(self, interface: str, runner: CommandRunner = subprocess_runner) -> None:
        self._interface = interface
        self._run = runner

    async def _run_checked(self, *args: str) -> str:
        code, stdout, stderr = await self._run(*args)
        if code != 0:
            WG_COMMAND_ERRORS_TOTAL.labels(command=args[0]).inc()
            raise WireGuardCommandError(args, code, stderr)
        return stdout

    async def add_or_update_peer(self, public_key: str, allowed_ips: list[str]) -> None:
        await self._run_checked(
            "wg", "set", self._interface, "peer", public_key, "allowed-ips", ",".join(allowed_ips)
        )

    async def remove_peer(self, public_key: str) -> None:
        await self._run_checked("wg", "set", self._interface, "peer", public_key, "remove")

    async def save_config(self) -> None:
        """Persists the live interface state so it survives a reboot / wg-quick restart."""
        await self._run_checked("wg-quick", "save", self._interface)

    async def dump(self) -> list[PeerStats]:
        stdout = await self._run_checked("wg", "show", self._interface, "dump")
        return parse_wg_dump(stdout)


_HANDSHAKE_ZERO = 0


def parse_wg_dump(raw: str) -> list[PeerStats]:
    """Parses `wg show <iface> dump` output. The first line (interface itself) is skipped;
    each subsequent line is one peer: pubkey psk endpoint allowed-ips latest-hs rx tx keepalive.
    """
    lines = [line for line in raw.strip().splitlines() if line.strip()]
    peers: list[PeerStats] = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) < 8:
            continue
        public_key, _psk, endpoint, allowed_ips_raw, latest_hs, rx, tx, _keepalive = fields[:8]
        handshake_epoch = int(latest_hs) if re.fullmatch(r"\d+", latest_hs) else _HANDSHAKE_ZERO
        peers.append(
            PeerStats(
                public_key=public_key,
                endpoint=None if endpoint == "(none)" else endpoint,
                allowed_ips=[a for a in allowed_ips_raw.split(",") if a and a != "(none)"],
                latest_handshake=(
                    datetime.fromtimestamp(handshake_epoch, tz=UTC)
                    if handshake_epoch > _HANDSHAKE_ZERO
                    else None
                ),
                rx_bytes=int(rx) if rx.isdigit() else 0,
                tx_bytes=int(tx) if tx.isdigit() else 0,
            )
        )
    return peers
