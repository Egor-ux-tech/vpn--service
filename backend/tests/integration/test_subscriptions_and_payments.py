import orjson
import pytest

from app.core.config import get_settings
from app.core.security import sign_hmac
from app.repositories.payment_repository import PaymentRepository


def _sign(payload: dict) -> str:
    settings = get_settings()
    return sign_hmac(orjson.dumps(payload), settings.payment_webhook_secret)


@pytest.mark.asyncio
async def test_creating_a_payment_leaves_subscription_pending_not_active(
    client, internal_headers, sample_plan
):
    """A subscription must never become active just because the user pressed 'pay' —
    only a confirmed webhook may activate it."""
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 1001}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "1001"}

    create_resp = await client.post(
        "/api/v1/payments", json={"plan_id": sample_plan.id}, headers=user_headers
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["status"] == "pending"

    active = await client.get("/api/v1/subscriptions/me/active", headers=user_headers)
    assert active.json() is None


@pytest.mark.asyncio
async def test_webhook_activates_subscription_and_is_idempotent(
    client, internal_headers, sample_plan, db_session
):
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 1002}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "1002"}

    create_resp = await client.post(
        "/api/v1/payments", json={"plan_id": sample_plan.id}, headers=user_headers
    )
    payment_id = create_resp.json()["payment_id"]

    repo = PaymentRepository(db_session)
    payment = await repo.get(payment_id)
    external_id = payment.external_payment_id

    webhook_body = {
        "external_payment_id": external_id,
        "status": "succeeded",
        "amount": str(sample_plan.price),
        "currency": "RUB",
    }
    signature = _sign(webhook_body)

    first = await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": signature},
    )
    assert first.status_code == 200

    active = await client.get("/api/v1/subscriptions/me/active", headers=user_headers)
    assert active.json() is not None
    assert active.json()["status"] == "active"
    first_expiry = active.json()["expires_at"]

    # Replay the same webhook — must not double-extend the subscription (idempotency).
    second = await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": signature},
    )
    assert second.status_code == 200

    active_after_replay = await client.get("/api/v1/subscriptions/me/active", headers=user_headers)
    assert active_after_replay.json()["expires_at"] == first_expiry


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client):
    webhook_body = {
        "external_payment_id": "mock_doesnotexist",
        "status": "succeeded",
        "amount": "1.00",
        "currency": "RUB",
    }
    resp = await client.post(
        "/api/v1/payments/webhook",
        content=orjson.dumps(webhook_body),
        headers={"X-Signature": "not-a-valid-signature"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cancel_subscription(client, internal_headers, sample_plan, db_session):
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 1003}, headers=internal_headers)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "1003"}

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

    active = await client.get("/api/v1/subscriptions/me/active", headers=user_headers)
    subscription_id = active.json()["id"]

    cancel_resp = await client.post(
        f"/api/v1/subscriptions/{subscription_id}/cancel", headers=user_headers
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"
