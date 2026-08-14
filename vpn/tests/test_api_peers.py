import time

import orjson
import pytest

from tests.conftest import sign


@pytest.mark.asyncio
async def test_create_peer_returns_private_key_once(client):
    body = orjson.dumps({"device_id": 1, "assigned_ip": "10.66.0.2/32"})
    resp = await client.post("/peers", content=body, headers=sign(body))

    assert resp.status_code == 201
    data = resp.json()
    assert "private_key" in data
    assert data["assigned_ip"] == "10.66.0.2/32"


@pytest.mark.asyncio
async def test_create_peer_rejects_missing_signature(client):
    body = orjson.dumps({"device_id": 1, "assigned_ip": "10.66.0.2/32"})
    resp = await client.post("/peers", content=body)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_peer_rejects_invalid_signature(client):
    body = orjson.dumps({"device_id": 1, "assigned_ip": "10.66.0.2/32"})
    resp = await client.post(
        "/peers",
        content=body,
        headers={"X-Signature": "wrong", "X-Timestamp": str(int(time.time()))},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_peer_rejects_stale_timestamp(client):
    body = orjson.dumps({"device_id": 1, "assigned_ip": "10.66.0.2/32"})
    headers = sign(body)
    headers["X-Timestamp"] = str(int(time.time()) - 999)
    resp = await client.post("/peers", content=body, headers=headers)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_disable_then_enable_peer(client):
    create_body = orjson.dumps({"device_id": 2, "assigned_ip": "10.66.0.3/32"})
    create_resp = await client.post("/peers", content=create_body, headers=sign(create_body))
    public_key = create_resp.json()["public_key"]

    disable_resp = await client.post(
        "/peers/disable", content=b"", headers=sign(b""), params={"public_key": public_key}
    )
    assert disable_resp.status_code == 204

    status_resp = await client.get(
        "/peers/status", headers=sign(b""), params={"public_key": public_key}
    )
    assert status_resp.json()["status"] == "disabled"

    enable_resp = await client.post(
        "/peers/enable", content=b"", headers=sign(b""), params={"public_key": public_key}
    )
    assert enable_resp.status_code == 204


@pytest.mark.asyncio
async def test_disable_unknown_peer_returns_404(client):
    resp = await client.post(
        "/peers/disable", content=b"", headers=sign(b""), params={"public_key": "UNKNOWN"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_peer(client):
    create_body = orjson.dumps({"device_id": 3, "assigned_ip": "10.66.0.4/32"})
    create_resp = await client.post("/peers", content=create_body, headers=sign(create_body))
    public_key = create_resp.json()["public_key"]

    delete_resp = await client.request(
        "DELETE", "/peers", headers=sign(b""), params={"public_key": public_key}
    )
    assert delete_resp.status_code == 204

    status_resp = await client.get(
        "/peers/status", headers=sign(b""), params={"public_key": public_key}
    )
    assert status_resp.status_code == 404


@pytest.mark.asyncio
async def test_peer_key_containing_slashes_and_padding_round_trips(app, client):
    """Regression test: base64 public keys routinely contain '/', '+', '=' — routing by
    query parameter (not URL path segment) must round-trip these correctly, unlike a path
    segment where an ASGI server decodes '%2F' into a literal '/' before routing."""
    tricky_key = "aB/cD+eF/gH+iJkLmNoPqRsTuVwXyZ012345678901="
    await app.state.reconciler.add_peer(
        public_key=tricky_key, device_id=4, assigned_ip="10.66.0.5/32"
    )

    disable_resp = await client.post(
        "/peers/disable", content=b"", headers=sign(b""), params={"public_key": tricky_key}
    )
    assert disable_resp.status_code == 204

    status_resp = await client.get(
        "/peers/status", headers=sign(b""), params={"public_key": tricky_key}
    )
    assert status_resp.json()["status"] == "disabled"


@pytest.mark.asyncio
async def test_health_and_ready_do_not_require_signature(client):
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/ready")).status_code == 200
