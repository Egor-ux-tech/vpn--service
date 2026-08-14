"""UserReconciler.reconcile() — the self-healing mechanism that repopulates Xray's live
inbound after a crash/restart (add-missing) and prunes users Xray still has live but the
desired state no longer wants (remove-extra) — see reconciler.py's module docstring for
why both directions matter for Xray specifically, unlike vpn-agent's WireGuard peers.
"""

import pytest

from app.state.user_store import UserStore
from app.xray.reconciler import UserReconciler
from tests.fakes import FakeXrayHandlerClient


@pytest.mark.asyncio
async def test_reconcile_repopulates_after_simulated_xray_restart():
    fake = FakeXrayHandlerClient()
    store = UserStore(":memory:")
    reconciler = UserReconciler(fake, store, "vless-reality-in", True)

    await reconciler.add_user(uuid="u1", device_id=1, flow="xtls-rprx-vision")
    await reconciler.add_user(uuid="u2", device_id=2, flow="xtls-rprx-vision")
    assert len(fake.live["vless-reality-in"]) == 2

    fake.simulate_xray_restart()
    assert fake.live == {}

    result = await reconciler.reconcile(trigger="periodic")
    assert set(result.added) == {"device-1", "device-2"}
    assert result.removed == []
    assert set(fake.live["vless-reality-in"]) == {"device-1", "device-2"}


@pytest.mark.asyncio
async def test_reconcile_prunes_live_user_not_in_desired_state():
    """Simulates the backend having called DELETE while this agent was unreachable —
    Xray still has a stale live entry the desired state no longer wants. Periodic
    reconciliation must remove it, not just add missing ones."""
    fake = FakeXrayHandlerClient()
    store = UserStore(":memory:")
    reconciler = UserReconciler(fake, store, "vless-reality-in", True)

    await reconciler.add_user(uuid="u1", device_id=1, flow="xtls-rprx-vision")
    # A user Xray has live but that never made it into (or was already removed from)
    # the desired-state store.
    fake.live["vless-reality-in"]["device-99-orphan"] = "some-other-uuid"

    result = await reconciler.reconcile(trigger="periodic")
    assert result.removed == ["device-99-orphan"]
    assert "device-99-orphan" not in fake.live["vless-reality-in"]
    assert "device-1" in fake.live["vless-reality-in"]


@pytest.mark.asyncio
async def test_reconcile_is_noop_when_already_converged():
    fake = FakeXrayHandlerClient()
    store = UserStore(":memory:")
    reconciler = UserReconciler(fake, store, "vless-reality-in", True)
    await reconciler.add_user(uuid="u1", device_id=1, flow="xtls-rprx-vision")
    fake.calls.clear()

    result = await reconciler.reconcile(trigger="periodic")
    assert result.added == []
    assert result.removed == []
    assert fake.calls == []


@pytest.mark.asyncio
async def test_startup_reconcile_runs_in_dry_mode_without_touching_xray():
    """apply_to_live=False (local/dev/test without a real Xray) must never call the
    handler client at all — mirrors vpn-agent's apply_to_live_interface=False."""
    fake = FakeXrayHandlerClient()
    store = UserStore(":memory:")
    reconciler = UserReconciler(fake, store, "vless-reality-in", False)

    await reconciler.add_user(uuid="u1", device_id=1, flow="xtls-rprx-vision")
    result = await reconciler.reconcile(trigger="startup")

    assert fake.calls == []
    assert fake.live == {}
    assert result.added == []
    assert result.removed == []
    record = await store.get("u1")
    assert record is not None
