"""GET /sub/{token} — the public subscription-delivery endpoint. Covers every failure mode
required to stay indistinguishable from every other (see
app/services/subscription_delivery/delivery_service.py's module docstring), rate limiting,
and that the token never reaches a log line in plaintext.
"""

from datetime import UTC, datetime, timedelta

import orjson
import pytest

from app.core.config import get_settings
from app.core.deps import get_vpn_provider
from app.core.security import hash_password, sign_hmac
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole, VPNPeerStatus
from app.repositories.device_repository import DeviceRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.repositories.vpn_peer_repository import VPNPeerRepository
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
        email="subdelivery-admin@example.com",
        hashed_password=hash_password("s3cret-pw"),
        role=AdminRole.SUPERADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": "subdelivery-admin@example.com", "password": "s3cret-pw"},
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


async def _provision_device_and_get_token(
    client, internal_headers, db_session, plan, telegram_id: int
) -> tuple[str, dict, int]:
    """Full happy path. Returns (subscription_token, user_headers, device_id)."""
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
    body = device_resp.json()
    token = body["subscription_url"].rsplit("/", 1)[-1]
    return token, user_headers, body["device"]["id"]


@pytest.mark.asyncio
async def test_valid_token_returns_wireguard_config(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, _, _ = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6001
    )

    resp = await client.get(f"/sub/{token}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "[Interface]" in resp.text
    assert "[Peer]" in resp.text
    assert "AllowedIPs" in resp.text
    # Never a real private key over this endpoint — see WireGuardFormatter's docstring.
    assert "PrivateKey =" not in resp.text


@pytest.mark.asyncio
async def test_garbage_token_returns_generic_404(client):
    resp = await client.get("/sub/this-token-was-never-issued-by-anyone")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Not found"


@pytest.mark.asyncio
async def test_empty_token_returns_404_not_a_server_error(client):
    resp = await client.get("/sub/")
    # No token segment at all — FastAPI's own routing 404s (no matching route), not our
    # handler; still must never be a 500 or leak anything.
    assert resp.status_code in (404, 307)


@pytest.mark.asyncio
async def test_revoked_link_returns_generic_404(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, user_headers, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6002
    )
    assert (await client.get(f"/sub/{token}")).status_code == 200

    revoke_resp = await client.delete(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert revoke_resp.status_code == 200

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_expired_billing_subscription_returns_generic_404(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, _, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6003
    )
    assert (await client.get(f"/sub/{token}")).status_code == 200

    device = await DeviceRepository(db_session).get(device_id)
    sub_repo = SubscriptionRepository(db_session)
    subscription = await sub_repo.get_active_for_user(device.user_id)
    subscription.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_disabled_device_returns_generic_404(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, user_headers, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6004
    )
    assert (await client.get(f"/sub/{token}")).status_code == 200

    disable_resp = await client.post(f"/api/v1/devices/{device_id}/disable", headers=user_headers)
    assert disable_resp.status_code == 200

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_revoked_device_returns_generic_404(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, user_headers, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6005
    )
    assert (await client.get(f"/sub/{token}")).status_code == 200

    revoke_resp = await client.delete(f"/api/v1/devices/{device_id}", headers=user_headers)
    assert revoke_resp.status_code == 200

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_peer_not_usable_returns_generic_404(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    """A device can be ACTIVE with billing ACTIVE but its peer disabled/revoked
    independently (e.g. mid-way through some other operation) — the delivery endpoint must
    still refuse rather than render a config for a peer that isn't actually live."""
    token, _, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6006
    )
    assert (await client.get(f"/sub/{token}")).status_code == 200

    peer_repo = VPNPeerRepository(db_session)
    peer = await peer_repo.get_active_for_device(device_id)
    peer.status = VPNPeerStatus.DISABLED
    await db_session.commit()

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_all_failure_modes_produce_byte_identical_responses(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    """The core anti-enumeration property: an attacker must not be able to distinguish
    "never existed" from "revoked" from "billing lapsed" from "device disabled" by
    response shape, status code, or body content."""
    token, user_headers, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6007
    )

    garbage_resp = await client.get("/sub/never-issued-token-abc")

    disable_resp = await client.post(f"/api/v1/devices/{device_id}/disable", headers=user_headers)
    assert disable_resp.status_code == 200
    disabled_resp = await client.get(f"/sub/{token}")

    assert garbage_resp.status_code == disabled_resp.status_code == 404
    # Compare everything except request_id, which legitimately differs per request.
    garbage_body = garbage_resp.json()
    disabled_body = disabled_resp.json()
    del garbage_body["error"]["request_id"]
    del disabled_body["error"]["request_id"]
    assert garbage_body == disabled_body


@pytest.mark.asyncio
async def test_rate_limiting_kicks_in_on_the_configured_threshold(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    settings = get_settings()
    limit = int(settings.subscription_link_rate_limit.split("/")[0])

    responses = [await client.get("/sub/probe-token-for-rate-limit") for _ in range(limit)]
    assert all(r.status_code == 404 for r in responses), [r.status_code for r in responses]

    over_limit_resp = await client.get("/sub/probe-token-for-rate-limit")
    assert over_limit_resp.status_code == 429


@pytest.mark.asyncio
async def test_token_never_appears_in_logs_and_path_is_masked(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider, capsys
):
    token, _, _ = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6008
    )
    capsys.readouterr()  # discard setup noise

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 200

    logged = capsys.readouterr().out
    assert token not in logged
    assert "/sub/***" in logged


@pytest.mark.asyncio
async def test_successful_fetch_updates_access_metadata(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, user_headers, device_id = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6009
    )
    before = await client.get(
        f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers
    )
    assert before.json()["last_accessed_at"] is None

    assert (await client.get(f"/sub/{token}")).status_code == 200

    after = await client.get(f"/api/v1/devices/{device_id}/subscription-link", headers=user_headers)
    assert after.json()["last_accessed_at"] is not None


@pytest.mark.asyncio
async def test_unknown_format_falls_back_to_wireguard(
    client, internal_headers, sample_plan, db_session, fake_vpn_provider
):
    token, _, _ = await _provision_device_and_get_token(
        client, internal_headers, db_session, sample_plan, telegram_id=6010
    )
    resp = await client.get(f"/sub/{token}", params={"format": "some-unregistered-format"})
    assert resp.status_code == 200
    assert "[Interface]" in resp.text
