import pytest

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_bootstrap_creates_first_admin(client):
    settings = get_settings()
    resp = await client.post(
        "/api/v1/auth/admin/bootstrap",
        json={
            "secret": settings.admin_secret,
            "email": "root@example.com",
            "password": "s3cret-password",
        },
    )
    assert resp.status_code == 201
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_bootstrap_rejects_wrong_secret(client):
    resp = await client.post(
        "/api/v1/auth/admin/bootstrap",
        json={
            "secret": "totally-wrong",
            "email": "root@example.com",
            "password": "s3cret-password",
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bootstrap_only_works_once(client):
    settings = get_settings()
    payload = {
        "secret": settings.admin_secret,
        "email": "root@example.com",
        "password": "s3cret-password",
    }

    first = await client.post("/api/v1/auth/admin/bootstrap", json=payload)
    assert first.status_code == 201

    second_payload = {**payload, "email": "someone-else@example.com"}
    second = await client.post("/api/v1/auth/admin/bootstrap", json=second_payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "bootstrap_already_completed"


@pytest.mark.asyncio
async def test_bootstrapped_admin_can_log_in(client):
    settings = get_settings()
    await client.post(
        "/api/v1/auth/admin/bootstrap",
        json={
            "secret": settings.admin_secret,
            "email": "root@example.com",
            "password": "s3cret-password",
        },
    )

    login = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "root@example.com", "password": "s3cret-password"},
    )
    assert login.status_code == 200
