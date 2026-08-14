import pytest


@pytest.mark.asyncio
async def test_create_and_reply_to_support_ticket(client, internal_headers, db_session):
    from app.core.security import hash_password
    from app.models.admin_user import AdminUser
    from app.models.enums import AdminRole

    admin = AdminUser(
        email="support@example.com",
        hashed_password=hash_password("s3cret-pw"),
        role=AdminRole.SUPPORT,
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login", json={"email": "support@example.com", "password": "s3cret-pw"}
    )
    admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    await client.post("/api/v1/auth/telegram", json={"telegram_id": 4001}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "4001"}

    create_resp = await client.post(
        "/api/v1/support",
        json={"subject": "VPN not connecting", "message": "I get a handshake timeout"},
        headers=user_headers,
    )
    assert create_resp.status_code == 201
    ticket_id = create_resp.json()["id"]
    assert len(create_resp.json()["messages"]) == 1

    reply_resp = await client.post(
        f"/api/v1/support/{ticket_id}/reply",
        json={"text": "Please try re-generating your config."},
        headers=admin_headers,
    )
    assert reply_resp.status_code == 201

    ticket_resp = await client.get(f"/api/v1/support/{ticket_id}", headers=user_headers)
    assert len(ticket_resp.json()["messages"]) == 2
    assert ticket_resp.json()["status"] == "pending"

    close_resp = await client.post(f"/api/v1/support/{ticket_id}/close", headers=admin_headers)
    assert close_resp.json()["status"] == "closed"
