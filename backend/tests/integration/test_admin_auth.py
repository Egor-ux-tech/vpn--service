import pytest

from app.core.security import hash_password
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole


async def _create_admin(db_session, *, role=AdminRole.SUPERADMIN) -> AdminUser:
    admin = AdminUser(
        email="admin@example.com", hashed_password=hash_password("s3cret-pw"), role=role
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest.mark.asyncio
async def test_admin_login_succeeds_with_correct_credentials(client, db_session):
    await _create_admin(db_session)

    resp = await client.post(
        "/api/v1/auth/admin/login", json={"email": "admin@example.com", "password": "s3cret-pw"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    # No refresh-token mechanism exists (see tests/unit/test_security_tokens.py) — the
    # login response must not imply one by carrying a token nothing ever consumes.
    assert "refresh_token" not in body


@pytest.mark.asyncio
async def test_admin_login_rejects_wrong_password(client, db_session):
    await _create_admin(db_session)

    resp = await client.post(
        "/api/v1/auth/admin/login", json={"email": "admin@example.com", "password": "wrong"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_requires_admin_token(client):
    resp = await client.get("/api/v1/admin/dashboard")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_accessible_with_valid_admin_token(client, db_session):
    await _create_admin(db_session)
    login = await client.post(
        "/api/v1/auth/admin/login", json={"email": "admin@example.com", "password": "s3cret-pw"}
    )
    token = login.json()["access_token"]

    resp = await client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "total_users" in resp.json()


@pytest.mark.asyncio
async def test_plan_creation_requires_superadmin_role(client, db_session):
    await _create_admin(db_session, role=AdminRole.VIEWER)
    login = await client.post(
        "/api/v1/auth/admin/login", json={"email": "admin@example.com", "password": "s3cret-pw"}
    )
    token = login.json()["access_token"]

    resp = await client.post(
        "/api/v1/plans",
        json={
            "name": "Basic",
            "slug": "basic",
            "price": "99.00",
            "duration_days": 30,
            "max_devices": 1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
