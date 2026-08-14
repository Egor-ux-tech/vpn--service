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
        email="ops@example.com",
        hashed_password=hash_password("s3cret-pw"),
        role=AdminRole.SUPERADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login", json={"email": "ops@example.com", "password": "s3cret-pw"}
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
    # Mark the server ONLINE so it's eligible for auto-selection.
    await client.patch(
        f"/api/v1/servers/{server_id}",
        json={"status": "online"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return server_id


async def _activate_subscription(client, internal_headers, plan, telegram_id: int) -> dict:
    await client.post(
        "/api/v1/auth/telegram", json={"telegram_id": telegram_id}, headers=internal_headers
    )
    user_headers = {**internal_headers, "X-Telegram-User-Id": str(telegram_id)}
    create_resp = await client.post(
        "/api/v1/payments", json={"plan_id": plan.id}, headers=user_headers
    )
    payment_id = create_resp.json()["payment_id"]
    return user_headers, payment_id


@pytest.mark.asyncio
async def test_device_provisioning_creates_peer_and_returns_config(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    await _create_server(client, db_session)
    user_headers, payment_id = await _activate_subscription(
        client, internal_headers, sample_plan, telegram_id=2001
    )

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

    create_device = await client.post(
        "/api/v1/devices", json={"name": "My iPhone"}, headers=user_headers
    )
    assert create_device.status_code == 201
    body = create_device.json()
    assert "PrivateKey" in body["config_text"]
    assert body["qr_code_base64"]
    assert body["device"]["status"] == "active"
    assert len(fake_vpn_provider.created) == 1


@pytest.mark.asyncio
async def test_device_provisioning_without_subscription_is_rejected(
    client, internal_headers, fake_vpn_provider
):
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 2002}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "2002"}

    resp = await client.post("/api/v1/devices", json={"name": "Laptop"}, headers=user_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_device_limit_is_enforced(client, internal_headers, db_session, fake_vpn_provider):
    from app.models.plan import Plan

    single_device_plan = Plan(
        name="Solo", slug="solo", price="49.00", currency="RUB", duration_days=30, max_devices=1
    )
    db_session.add(single_device_plan)
    await db_session.commit()
    await db_session.refresh(single_device_plan)

    await _create_server(client, db_session)
    user_headers, payment_id = await _activate_subscription(
        client, internal_headers, single_device_plan, telegram_id=2003
    )
    repo = PaymentRepository(db_session)
    payment = await repo.get(payment_id)
    webhook_body = {
        "external_payment_id": payment.external_payment_id,
        "status": "succeeded",
        "amount": str(single_device_plan.price),
        "currency": "RUB",
    }
    await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": _sign(webhook_body)},
    )

    first = await client.post("/api/v1/devices", json={"name": "Phone"}, headers=user_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/devices", json={"name": "Laptop"}, headers=user_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "device_limit_reached"


@pytest.mark.asyncio
async def test_revoking_a_device_deletes_the_vpn_peer(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    await _create_server(client, db_session)
    user_headers, payment_id = await _activate_subscription(
        client, internal_headers, sample_plan, telegram_id=2004
    )
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

    create_device = await client.post(
        "/api/v1/devices", json={"name": "Tablet"}, headers=user_headers
    )
    device_id = create_device.json()["device"]["id"]

    revoke_resp = await client.delete(f"/api/v1/devices/{device_id}", headers=user_headers)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"
    assert len(fake_vpn_provider.deleted) == 1


@pytest.mark.asyncio
async def test_disable_and_enable_device(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    await _create_server(client, db_session)
    user_headers, payment_id = await _activate_subscription(
        client, internal_headers, sample_plan, telegram_id=2005
    )
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
    create_device = await client.post(
        "/api/v1/devices", json={"name": "Desktop"}, headers=user_headers
    )
    device_id = create_device.json()["device"]["id"]

    disable_resp = await client.post(f"/api/v1/devices/{device_id}/disable", headers=user_headers)
    assert disable_resp.status_code == 200
    assert disable_resp.json()["status"] == "disabled"
    assert fake_vpn_provider.disabled

    enable_resp = await client.post(f"/api/v1/devices/{device_id}/enable", headers=user_headers)
    assert enable_resp.status_code == 200
    assert enable_resp.json()["status"] == "active"
    assert fake_vpn_provider.enabled
