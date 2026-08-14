"""Recovery after the *agent* process itself restarts (distinct from Xray restarting —
see test_reconciliation.py): the desired-state store is durable on disk, so a fresh
UserStore/UserReconciler pointed at the same file must see everything the previous
process instance wrote, and startup reconciliation must repopulate Xray from it."""

import pytest

from app.state.user_store import UserStore
from app.xray.reconciler import UserReconciler
from tests.fakes import FakeXrayHandlerClient


@pytest.mark.asyncio
async def test_desired_state_survives_a_fresh_store_instance_against_the_same_file(tmp_path):
    db_path = str(tmp_path / "state.db")
    fake = FakeXrayHandlerClient()

    store_a = UserStore(db_path)
    reconciler_a = UserReconciler(fake, store_a, "vless-reality-in", True)
    await reconciler_a.add_user(uuid="u1", device_id=1, flow="xtls-rprx-vision")
    await reconciler_a.add_user(uuid="u2", device_id=2, flow="xtls-rprx-vision")

    # Simulate the agent process restarting: brand-new UserStore/UserReconciler
    # instances, same on-disk file, and Xray having also been bounced (empty live set)
    # — the worst case, both processes lost their in-memory state simultaneously.
    fake.simulate_xray_restart()
    store_b = UserStore(db_path)
    reconciler_b = UserReconciler(fake, store_b, "vless-reality-in", True)

    records = await reconciler_b.list_users()
    assert {r.uuid for r in records} == {"u1", "u2"}

    result = await reconciler_b.reconcile(trigger="startup")
    assert set(result.added) == {"device-1", "device-2"}
    assert set(fake.live["vless-reality-in"]) == {"device-1", "device-2"}
