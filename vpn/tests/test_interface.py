import pytest

from app.wireguard.interface import WireGuardCommandError, WireGuardInterface


class _RecordingRunner:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[tuple[str, ...]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def __call__(self, *args: str) -> tuple[int, str, str]:
        self.calls.append(args)
        return self._returncode, self._stdout, self._stderr


@pytest.mark.asyncio
async def test_add_or_update_peer_invokes_wg_set_with_allowed_ips():
    runner = _RecordingRunner()
    iface = WireGuardInterface("wg0", runner=runner)

    await iface.add_or_update_peer("PUBKEY", ["10.66.0.2/32"])

    assert runner.calls == [("wg", "set", "wg0", "peer", "PUBKEY", "allowed-ips", "10.66.0.2/32")]


@pytest.mark.asyncio
async def test_remove_peer_invokes_wg_set_remove():
    runner = _RecordingRunner()
    iface = WireGuardInterface("wg0", runner=runner)

    await iface.remove_peer("PUBKEY")

    assert runner.calls == [("wg", "set", "wg0", "peer", "PUBKEY", "remove")]


@pytest.mark.asyncio
async def test_command_failure_raises_without_leaking_key_material():
    runner = _RecordingRunner(returncode=1, stderr="device wg0 does not exist")
    iface = WireGuardInterface("wg0", runner=runner)

    with pytest.raises(WireGuardCommandError) as exc_info:
        await iface.remove_peer("PUBKEY")

    assert "does not exist" in str(exc_info.value)
