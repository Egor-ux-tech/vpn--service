import pytest


@pytest.mark.asyncio
async def test_telegram_auth_creates_user(client, internal_headers):
    resp = await client.post(
        "/api/v1/auth/telegram",
        json={"telegram_id": 555, "username": "newbie"},
        headers=internal_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["telegram_id"] == 555
    assert body["username"] == "newbie"
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_telegram_auth_rejects_missing_internal_token(client):
    resp = await client.post("/api/v1/auth/telegram", json={"telegram_id": 555})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_telegram_auth_is_idempotent_upsert(client, internal_headers):
    payload = {"telegram_id": 777, "username": "first"}
    first = await client.post("/api/v1/auth/telegram", json=payload, headers=internal_headers)
    payload["username"] = "renamed"
    second = await client.post("/api/v1/auth/telegram", json=payload, headers=internal_headers)

    assert first.json()["id"] == second.json()["id"]
    assert second.json()["username"] == "renamed"


@pytest.mark.asyncio
async def test_get_my_profile_requires_telegram_user_header(client, internal_headers):
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 888}, headers=internal_headers)
    resp = await client.get(
        "/api/v1/users/me",
        headers={**internal_headers, "X-Telegram-User-Id": "888"},
    )
    assert resp.status_code == 200
    assert resp.json()["telegram_id"] == 888


@pytest.mark.asyncio
async def test_blocked_user_is_rejected(client, internal_headers, db_session):
    from app.models.enums import UserStatus
    from app.models.user import User

    user = User(telegram_id=999, status=UserStatus.BLOCKED)
    db_session.add(user)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/users/me",
        headers={**internal_headers, "X-Telegram-User-Id": "999"},
    )
    assert resp.status_code == 403
