import pytest

from app.core.security import hash_password
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole


async def _admin_token(client, db_session) -> str:
    admin = AdminUser(
        email="routing-admin@example.com",
        hashed_password=hash_password("s3cret-pw"),
        role=AdminRole.SUPERADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "routing-admin@example.com", "password": "s3cret-pw"},
    )
    return login.json()["access_token"]


@pytest.mark.asyncio
async def test_smart_vpn_category_toggle_flow(client, internal_headers, db_session):
    token = await _admin_token(client, db_session)
    admin_headers = {"Authorization": f"Bearer {token}"}

    category_resp = await client.post(
        "/api/v1/routing/categories",
        json={"name": "Video", "description": "Streaming services"},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201
    category_id = category_resp.json()["id"]

    rule_resp = await client.post(
        "/api/v1/routing/rules",
        json={"category_id": category_id, "domain": "youtube.com", "route_type": "vpn"},
        headers=admin_headers,
    )
    assert rule_resp.status_code == 201

    await client.post("/api/v1/auth/telegram", json={"telegram_id": 3001}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "3001"}

    settings_before = await client.get("/api/v1/routing/me/settings", headers=user_headers)
    assert settings_before.json()["mode"] == "full_vpn"
    assert settings_before.json()["enabled_category_ids"] == []

    mode_resp = await client.put(
        "/api/v1/routing/me/mode", json={"mode": "smart_vpn"}, headers=user_headers
    )
    assert mode_resp.json()["mode"] == "smart_vpn"

    toggle_resp = await client.put(
        "/api/v1/routing/me/categories",
        json={"category_id": category_id, "enabled": True},
        headers=user_headers,
    )
    assert category_id in toggle_resp.json()["enabled_category_ids"]

    domain_resp = await client.post(
        "/api/v1/routing/me/domains",
        json={"domain": "my-custom-work-vpn.example.com", "route_type": "vpn"},
        headers=user_headers,
    )
    assert "my-custom-work-vpn.example.com" in domain_resp.json()["custom_domains"]


@pytest.mark.asyncio
async def test_list_categories_is_public(client):
    resp = await client.get("/api/v1/routing/categories")
    assert resp.status_code == 200
