"""In-memory test double for XrayHandlerClient — no real Xray process, no gRPC network
call. Mirrors the role vpn-agent's injectable CommandRunner plays for the `wg` CLI."""

from dataclasses import dataclass, field

from app.xray.handler_client import XrayCommandError


@dataclass
class FakeXrayHandlerClient:
    live: dict[str, dict[str, str]] = field(default_factory=dict)  # tag -> {email: uuid}
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    fail_next_calls: int = 0

    def _maybe_fail(self, operation: str) -> None:
        if self.fail_next_calls > 0:
            self.fail_next_calls -= 1
            raise XrayCommandError(f"simulated Xray failure for {operation!r}")

    async def add_user(self, *, tag: str, uuid: str, email: str, flow: str) -> None:
        self._maybe_fail("add_user")
        self.live.setdefault(tag, {})[email] = uuid
        self.calls.append(("add", tag, email))

    async def remove_user(self, *, tag: str, email: str) -> None:
        self._maybe_fail("remove_user")
        self.live.get(tag, {}).pop(email, None)
        self.calls.append(("remove", tag, email))

    async def list_user_emails(self, *, tag: str) -> list[str]:
        self._maybe_fail("list_user_emails")
        return list(self.live.get(tag, {}).keys())

    async def count_users(self, *, tag: str) -> int:
        self._maybe_fail("count_users")
        return len(self.live.get(tag, {}))

    def simulate_xray_restart(self) -> None:
        """Xray restarting wipes its in-memory user list back to empty — exactly what
        happens on the real thing (see UserReconciler's module docstring)."""
        self.live.clear()
