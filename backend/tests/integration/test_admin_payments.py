import pytest

from app.core.security import hash_password
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole


async def _admin_token(client, db_session, role: AdminRole = AdminRole.VIEWER) -> str:
    admin = AdminUser(
        email="payments-admin@example.com", hashed_password=hash_password("s3cret-pw"), role=role
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "payments-admin@example.com", "password": "s3cret-pw"},
    )
    return login.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_can_list_all_payments(client, internal_headers, sample_plan, db_session):
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 5001}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "5001"}
    await client.post("/api/v1/payments", json={"plan_id": sample_plan.id}, headers=user_headers)

    token = await _admin_token(client, db_session)
    resp = await client.get("/api/v1/payments", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_list_all_payments_requires_admin_auth(client):
    resp = await client.get("/api/v1/payments")
    assert resp.status_code == 401
