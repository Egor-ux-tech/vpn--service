import time

import orjson
import pytest

from tests.conftest import sign


@pytest.mark.asyncio
async def test_create_user_returns_201(client):
    body = orjson.dumps({"uuid": "11111111-1111-1111-1111-111111111111", "device_id": 1})
    resp = await client.post("/users", content=body, headers=sign(body))
    assert resp.status_code == 201
    data = resp.json()
    assert data["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert data["device_id"] == 1
    assert data["flow"] == "xtls-rprx-vision"


@pytest.mark.asyncio
async def test_create_user_calls_xray_add_user_exactly_once(client, fake_handler_client):
    body = orjson.dumps({"uuid": "22222222-2222-2222-2222-222222222222", "device_id": 2})
    resp = await client.post("/users", content=body, headers=sign(body))
    assert resp.status_code == 201
    assert fake_handler_client.calls == [("add", "vless-reality-in", "device-2")]


@pytest.mark.asyncio
async def test_create_user_is_idempotent(client, fake_handler_client):
    body = orjson.dumps({"uuid": "33333333-3333-3333-3333-333333333333", "device_id": 3})
    first = await client.post("/users", content=body, headers=sign(body))
    second = await client.post("/users", content=body, headers=sign(body))
    assert first.status_code == second.status_code == 201
    # Second call sees the user already live on Xray and makes no further gRPC call.
    assert fake_handler_client.calls == [("add", "vless-reality-in", "device-3")]


@pytest.mark.asyncio
async def test_create_user_rejects_missing_signature(client):
    body = orjson.dumps({"uuid": "44444444-4444-4444-4444-444444444444", "device_id": 4})
    resp = await client.post("/users", content=body)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_signature(client):
    body = orjson.dumps({"uuid": "55555555-5555-5555-5555-555555555555", "device_id": 5})
    headers = {"X-Signature": "wrong", "X-Timestamp": str(int(time.time()))}
    resp = await client.post("/users", content=body, headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_user_rejects_stale_timestamp(client):
    body = orjson.dumps({"uuid": "66666666-6666-6666-6666-666666666666", "device_id": 6})
    headers = sign(body)
    headers["X-Timestamp"] = str(int(time.time()) - 999)
    resp = await client.post("/users", content=body, headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_replayed_request_is_rejected_once_stale(client):
    """A captured (signature, timestamp) pair becomes unusable once it falls outside the
    freshness window — the core anti-replay property."""
    body = orjson.dumps({"uuid": "77777777-7777-7777-7777-777777777777", "device_id": 7})
    headers = sign(body)
    fresh = await client.post("/users", content=body, headers=headers)
    assert fresh.status_code == 201

    replayed_headers = dict(headers)
    replayed_headers["X-Timestamp"] = str(int(time.time()) - 999)
    replayed = await client.post("/users", content=body, headers=replayed_headers)
    assert replayed.status_code == 401


@pytest.mark.asyncio
async def test_delete_user_removes_from_xray_and_store(client, fake_handler_client):
    create_body = orjson.dumps({"uuid": "88888888-8888-8888-8888-888888888888", "device_id": 8})
    await client.post("/users", content=create_body, headers=sign(create_body))

    delete_resp = await client.delete(
        "/users/88888888-8888-8888-8888-888888888888", headers=sign(b"")
    )
    assert delete_resp.status_code == 204
    assert ("remove", "vless-reality-in", "device-8") in fake_handler_client.calls
    assert "device-8" not in fake_handler_client.live.get("vless-reality-in", {})


@pytest.mark.asyncio
async def test_delete_unknown_user_is_idempotent_success(client):
    resp = await client.delete("/users/99999999-9999-9999-9999-999999999999", headers=sign(b""))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_rotate_user_changes_uuid_keeps_device(client, fake_handler_client):
    create_body = orjson.dumps({"uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "device_id": 10})
    await client.post("/users", content=create_body, headers=sign(create_body))

    rotate_body = orjson.dumps({"new_uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"})
    rotate_resp = await client.post(
        "/users/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/rotate",
        content=rotate_body,
        headers=sign(rotate_body),
    )
    assert rotate_resp.status_code == 200
    data = rotate_resp.json()
    assert data["uuid"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert data["device_id"] == 10
    assert data["rotated_at"] is not None

    # Same Xray-side identity (email), old uuid gone, new uuid live.
    assert fake_handler_client.live["vless-reality-in"]["device-10"] == (
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )

    old_status = await client.get("/users", headers=sign(b""))
    uuids = [u["uuid"] for u in old_status.json()]
    assert "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" not in uuids
    assert "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" in uuids


@pytest.mark.asyncio
async def test_rotate_unknown_user_returns_404(client):
    rotate_body = orjson.dumps({"new_uuid": "cccccccc-cccc-cccc-cccc-cccccccccccc"})
    resp = await client.post(
        "/users/00000000-0000-0000-0000-000000000000/rotate",
        content=rotate_body,
        headers=sign(rotate_body),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_users_requires_signature(client):
    resp = await client.get("/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_users_returns_created_users(client):
    body = orjson.dumps({"uuid": "dddddddd-dddd-dddd-dddd-dddddddddddd", "device_id": 20})
    await client.post("/users", content=body, headers=sign(body))

    resp = await client.get("/users", headers=sign(b""))
    assert resp.status_code == 200
    uuids = [u["uuid"] for u in resp.json()]
    assert "dddddddd-dddd-dddd-dddd-dddddddddddd" in uuids


@pytest.mark.asyncio
async def test_create_user_surfaces_xray_unavailable_as_502(client, fake_handler_client):
    fake_handler_client.fail_next_calls = 1
    body = orjson.dumps({"uuid": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", "device_id": 30})
    resp = await client.post("/users", content=body, headers=sign(body))
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_health_and_ready_do_not_require_signature(client):
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/ready")).status_code == 200


@pytest.mark.asyncio
async def test_ready_reflects_xray_unreachable(client, fake_handler_client):
    fake_handler_client.fail_next_calls = 999
    resp = await client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["xray_reachable"] is False
    assert resp.json()["status"] == "degraded"


@pytest.mark.asyncio
async def test_status_reports_active_and_live_counts(client, fake_handler_client):
    body = orjson.dumps({"uuid": "ffffffff-ffff-ffff-ffff-ffffffffffff", "device_id": 40})
    await client.post("/users", content=body, headers=sign(body))

    resp = await client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_user_count"] == 1
    assert data["live_user_count"] == 1
    assert data["xray_reachable"] is True
