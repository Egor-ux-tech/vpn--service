import pytest

from app.state.peer_store import PeerStore


@pytest.fixture
def store():
    return PeerStore(":memory:")


@pytest.mark.asyncio
async def test_upsert_and_get(store):
    await store.upsert(public_key="PUB1", device_id=1, assigned_ip="10.66.0.2/32")
    record = await store.get("PUB1")
    assert record is not None
    assert record.device_id == 1
    assert record.enabled is True


@pytest.mark.asyncio
async def test_disable_then_enable(store):
    await store.upsert(public_key="PUB1", device_id=1, assigned_ip="10.66.0.2/32")
    await store.set_enabled("PUB1", False)
    assert (await store.get("PUB1")).enabled is False

    await store.set_enabled("PUB1", True)
    assert (await store.get("PUB1")).enabled is True


@pytest.mark.asyncio
async def test_delete_removes_record(store):
    await store.upsert(public_key="PUB1", device_id=1, assigned_ip="10.66.0.2/32")
    await store.delete("PUB1")
    assert await store.get("PUB1") is None


@pytest.mark.asyncio
async def test_list_enabled_excludes_disabled_peers(store):
    await store.upsert(public_key="PUB1", device_id=1, assigned_ip="10.66.0.2/32")
    await store.upsert(public_key="PUB2", device_id=2, assigned_ip="10.66.0.3/32")
    await store.set_enabled("PUB2", False)

    enabled = await store.list_enabled()
    assert {r.public_key for r in enabled} == {"PUB1"}


@pytest.mark.asyncio
async def test_get_missing_peer_returns_none(store):
    assert await store.get("does-not-exist") is None
