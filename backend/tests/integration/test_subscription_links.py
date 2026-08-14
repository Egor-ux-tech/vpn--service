"""Authenticated subscription-link management endpoints
(POST/GET/DELETE /api/v1/devices/{device_id}/subscription-link) and the auto-creation that
happens at device provisioning. See test_subscription_delivery.py for the public
GET /sub/{token} endpoint these links are for.
"""

import orjson
import pytest

from app.core.config import get_settings
from app.core.deps import get_vpn_provider
from app.core.security import hash_password, sign_hmac
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole
from app.repositories.payment_repository import PaymentRepository
from tests.fakes import FakeVPNProvider


def _sign(payload: dict) -> str:
    settings = get_settings()
    return sign_hmac(orjson.dumps(payload), settings.payment_webhook_secret)


@pytest.fixture
def fake_vpn_provider(app):
    provider = FakeVPNProvider()
    app.dependency_overrides[get_vpn_provider] = lambda: provider
    yield provider
    del app.dependency_overrides[get_vpn_provider]


async def _create_admin_token(client, db_session) -> str:
    admin = AdminUser(
        email="sublink-admin@example.com",
        hashed_password=hash_password("s3cret-pw"),
        role=AdminRole.SUPERADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "sublink-admin@example.com", "password": "s3cret-pw"},
    )
    return login.json()["access_token"]


async def _create_server(client, db_session) -> int:
    token = await _create_admin_token(client, db_session)
    resp = await client.post(
        "/api/v1/servers",
        json={
            "name": "NL-1",
            "country": "NL",
            "hostname": "nl1.example.com",
            "agent_base_url": "https://nl1.example.com:8800",
            "public_key": "SERVERPUBKEY",
            "endpoint": "nl1.example.com:51820",
            "internal_network": "10.66.0.0/24",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    server_id = resp.json()["id"]
    await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"status": "online"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return server_id


async def _activate_subscription_and_get_device(
    client, internal_headers, db_session, plan, telegram_id: int
) -> tuple[dict, int]:
    """Full happy path: server, user, paid subscription, one provisioned device. Returns
    (user_headers, device_id)."""
    await _create_server(client, db_session)
    await client.post(
        "/api/v1/auth/telegram", json={"telegram_id": telegram_id}, headers=internal_headers
    )
    user_headers = {**internal_headers, "X-Telegram-User-Id": str(telegram_id)}
    create_resp = await client.post(
        "/api/v1/payments", json={"plan_id": plan.id}, headers=user_headers
    )
    payment_id = create_resp.json()["payment_id"]

    repo = PaymentRepository(db_session)
    payment = await repo.get(payment_id)
    webhook_body = {
        "external_payment_id": payment.external_payment_id,
        "status": "succeeded",
        "amount": str(plan.price),
        "currency": "RUB",
    }
    await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": _sign(webhook_body)},
    )

    device_resp = await client.post(
        "/api/v1/devices", json={"name": "Test Device"}, headers=user_headers
    )
    assert device_resp.status_code == 201
    device_id = device_resp.json()["device"]["id"]
    return user_headers, device_id


@pytest.mark.asyncio
async def test_provisioning_automatically_creates_a_subscription_link(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    await _create_server(client, db_session)
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 5001}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "5001"}
    create_resp = await client.post(
        "/api/v1/payments", json={"plan_id": sample_plan.id}, headers=user_headers
    )
    payment_id = create_resp.json()["payment_id"]
    repo = PaymentRepository(db_session)
    payment = await repo.get(payment_id)
    webhook_body = {
        "external_payment_id": payment.external_payment_id,
        "status": "succeeded",
        "amount": str(sample_plan.price),
        "currency": "RUB",
    }
    await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": _sign(webhook_body)},
    )

    device_resp = await client.post(
        "/api/v1/devices", json={"name": "My Phone"}, headers=user_headers
    )
    assert device_resp.status_code == 201
    body = device_resp.json()

    assert body["subscription_url"] is not None
    assert body["subscription_url"].startswith("http")
    assert "/sub/" in body["subscription_url"]
    assert body["subscription_qr_code_base64"]

    device_id = body["device"]["id"]
    link_resp = await client.get(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert link_resp.status_code == 200
    link = link_resp.json()
    assert link["status"] == "active"
    assert link["device_id"] == device_id
    assert len(link["token_prefix"]) == 8
    # The metadata endpoint never re-exposes the token/URL itself (only its hash is
    # stored) — confirmed by absence, not just omission from the schema.
    assert "token" not in link
    assert "subscription_url" not in link
    assert "id" not in link  # no internal DB id leaked either


@pytest.mark.asyncio
async def test_reissue_does_not_return_a_new_subscription_url(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    user_headers, device_id = await _activate_subscription_and_get_device(
        client, internal_headers, db_session, sample_plan, telegram_id=5002
    )
    reissue_resp = await client.post(f"/api/v1/devices/{device_id}/reissue", headers=user_headers)
    assert reissue_resp.status_code == 200
    assert reissue_resp.json()["subscription_url"] is None
    assert reissue_resp.json()["subscription_qr_code_base64"] is None


@pytest.mark.asyncio
async def test_post_rotates_an_existing_link_and_invalidates_the_old_token(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    user_headers, device_id = await _activate_subscription_and_get_device(
        client, internal_headers, db_session, sample_plan, telegram_id=5003
    )

    # The device already has a link from auto-creation at provisioning — fetch its token
    # indirectly by rotating once to get a known plaintext value, then rotating again.
    first_rotate = await client.post(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert first_rotate.status_code == 201
    first_url = first_rotate.json()["subscription_url"]
    first_token = first_url.rsplit("/", 1)[-1]

    # The first token works right now.
    ok_resp = await client.get(f"/sub/{first_token}")
    assert ok_resp.status_code == 200

    second_rotate = await client.post(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert second_rotate.status_code == 201
    second_url = second_rotate.json()["subscription_url"]
    second_token = second_url.rsplit("/", 1)[-1]

    assert second_token != first_token

    # The old token is dead immediately; the new one works.
    old_resp = await client.get(f"/sub/{first_token}")
    assert old_resp.status_code == 404
    new_resp = await client.get(f"/sub/{second_token}")
    assert new_resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_revokes_the_link(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    user_headers, device_id = await _activate_subscription_and_get_device(
        client, internal_headers, db_session, sample_plan, telegram_id=5004
    )
    rotate_resp = await client.post(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    token = rotate_resp.json()["subscription_url"].rsplit("/", 1)[-1]
    assert (await client.get(f"/sub/{token}")).status_code == 200

    delete_resp = await client.delete(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "revoked"

    assert (await client.get(f"/sub/{token}")).status_code == 404

    get_resp = await client.get(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert get_resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_cannot_manage_another_users_device_subscription_link(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    _, device_id = await _activate_subscription_and_get_device(
        client, internal_headers, db_session, sample_plan, telegram_id=5005
    )

    await client.post("/api/v1/auth/telegram", json={"telegram_id": 5006}, headers=internal_headers)
    other_user_headers = {**internal_headers, "X-Telegram-User-Id": "5006"}

    resp = await client.get(
        f"/api/v1/devices/{device_id}/subscription-link", headers=other_user_headers
    )
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/devices/{device_id}/subscription-link", headers=other_user_headers
    )
    assert resp.status_code == 404

    resp = await client.delete(
        f"/api/v1/devices/{device_id}/subscription-link", headers=other_user_headers
    )
    assert resp.status_code == 404
