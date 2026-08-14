"""End-to-end VLESS device lifecycle through the real HTTP API: server registration,
provisioning (via a fake xray-agent, never a real Xray process — see docs/xray-agent.md
on why CI never needs one), subscription delivery, disable/enable/revoke, reissue
rejection, and expiry — proving the whole chain designed in docs/vless.md actually wires
together, not just each piece in isolation.
"""

import orjson
import pytest

from app.core.config import get_settings
from app.core.deps import get_xray_agent_provider
from app.core.security import hash_password, sign_hmac
from app.models.admin_user import AdminUser
from app.models.enums import AdminRole, VLESSCredentialStatus
from app.repositories.payment_repository import PaymentRepository
from app.repositories.vless_credential_repository import VLESSCredentialRepository
from tests.fakes import FakeXrayAgentProvider


def _sign(payload: dict) -> str:
    settings = get_settings()
    return sign_hmac(orjson.dumps(payload), settings.payment_webhook_secret)


@pytest.fixture
def fake_xray_agent_provider(app):
    provider = FakeXrayAgentProvider()
    app.dependency_overrides[get_xray_agent_provider] = lambda: provider
    yield provider
    del app.dependency_overrides[get_xray_agent_provider]


_admin_counter = {"n": 0}


async def _create_admin_token(client, db_session) -> str:
    _admin_counter["n"] += 1
    email = f"vless-admin-{_admin_counter['n']}@example.com"
    admin = AdminUser(
        email=email,
        hashed_password=hash_password("s3cret-pw"),
        role=AdminRole.SUPERADMIN,
    )
    db_session.add(admin)
    await db_session.commit()
    login = await client.post(
        "/api/v1/auth/admin/login",
        json={"email": email, "password": "s3cret-pw"},
    )
    return login.json()["access_token"]


async def _create_vless_server(client, db_session, *, hostname: str = "vless1.example.com") -> int:
    token = await _create_admin_token(client, db_session)
    resp = await client.post(
        "/api/v1/vless-servers",
        json={
            "name": "VLESS-NL-1",
            "country": "NL",
            "hostname": hostname,
            "xray_agent_base_url": "https://vless1.example.com:8801",
            "port": 443,
            "reality_public_key": "REALITYPUBKEY",
            "reality_short_ids": [""],
            "sni": "www.example.com",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    server_id = resp.json()["id"]
    await client.patch(
        f"/api/v1/vless-servers/{server_id}",
        json={"status": "online"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return server_id


async def _provision_vless_device(
    client, internal_headers, db_session, plan, telegram_id: int, name: str = "Phone"
) -> tuple[dict, dict, int]:
    """Full happy path. Returns (provisioning_result, user_headers, device_id)."""
    await _create_vless_server(client, db_session)
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
        "/api/v1/devices",
        json={"name": name, "protocol": "vless"},
        headers=user_headers,
    )
    assert device_resp.status_code == 201, device_resp.text
    body = device_resp.json()
    return body, user_headers, body["device"]["id"]


@pytest.mark.asyncio
async def test_vless_provisioning_creates_credential_and_calls_xray_agent(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    body, _, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9001
    )

    assert body["device"]["protocol"] == "vless"
    assert body["config_text"] is None
    assert body["qr_code_base64"] is None
    assert body["subscription_url"] is not None
    assert body["subscription_qr_code_base64"] is not None

    assert len(fake_xray_agent_provider.created) == 1

    cred_repo = VLESSCredentialRepository(db_session)
    credentials = await cred_repo.list_for_device(device_id)
    assert len(credentials) == 1
    assert credentials[0].status == VLESSCredentialStatus.ACTIVE
    assert credentials[0].uuid == fake_xray_agent_provider.created[0]


@pytest.mark.asyncio
async def test_vless_provisioning_never_creates_a_vpn_peer(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    from app.repositories.vpn_peer_repository import VPNPeerRepository

    _, _, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9002
    )

    peer_repo = VPNPeerRepository(db_session)
    peer = await peer_repo.get_active_for_device(device_id)
    assert peer is None


@pytest.mark.asyncio
async def test_vless_subscription_delivery_returns_vless_uri(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    body, _, _ = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9003
    )
    token = body["subscription_url"].rsplit("/", 1)[-1]

    resp = await client.get(f"/sub/{token}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text.startswith("vless://")
    assert "security=reality" in resp.text
    assert "PrivateKey" not in resp.text


@pytest.mark.asyncio
async def test_vless_device_disable_removes_from_xray_and_blocks_subscription(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    body, user_headers, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9004
    )
    token = body["subscription_url"].rsplit("/", 1)[-1]
    assert (await client.get(f"/sub/{token}")).status_code == 200

    disable_resp = await client.post(f"/api/v1/devices/{device_id}/disable", headers=user_headers)
    assert disable_resp.status_code == 200

    assert len(fake_xray_agent_provider.removed) == 1
    cred_repo = VLESSCredentialRepository(db_session)
    credentials = await cred_repo.list_for_device(device_id)
    assert credentials[0].status == VLESSCredentialStatus.DISABLED

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_vless_device_enable_re_adds_same_uuid(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    body, user_headers, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9005
    )
    token = body["subscription_url"].rsplit("/", 1)[-1]
    original_uuid = fake_xray_agent_provider.created[0]

    await client.post(f"/api/v1/devices/{device_id}/disable", headers=user_headers)
    enable_resp = await client.post(f"/api/v1/devices/{device_id}/enable", headers=user_headers)
    assert enable_resp.status_code == 200

    # Same UUID re-added, not rotated — disable/enable must be reversible without
    # invalidating whatever the user already has configured client-side.
    assert original_uuid in fake_xray_agent_provider.users

    cred_repo = VLESSCredentialRepository(db_session)
    credentials = await cred_repo.list_for_device(device_id)
    assert credentials[0].status == VLESSCredentialStatus.ACTIVE
    assert credentials[0].uuid == original_uuid

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 200
    assert original_uuid in resp.text


@pytest.mark.asyncio
async def test_vless_device_revoke_removes_from_xray_permanently(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    body, user_headers, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9006
    )
    token = body["subscription_url"].rsplit("/", 1)[-1]

    revoke_resp = await client.delete(f"/api/v1/devices/{device_id}", headers=user_headers)
    assert revoke_resp.status_code == 200

    assert len(fake_xray_agent_provider.removed) == 1
    cred_repo = VLESSCredentialRepository(db_session)
    credentials = await cred_repo.list_for_device(device_id)
    assert credentials[0].status == VLESSCredentialStatus.REVOKED
    assert credentials[0].revoked_at is not None

    resp = await client.get(f"/sub/{token}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_vless_reissue_is_rejected(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    _, user_headers, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9007
    )

    resp = await client.post(f"/api/v1/devices/{device_id}/reissue", headers=user_headers)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "reissue_not_supported_for_protocol"


@pytest.mark.asyncio
async def test_cannot_access_other_users_vless_subscription_via_wrong_token(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    body_a, _, _ = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9008, name="Phone A"
    )
    body_b, _, _ = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9009, name="Phone B"
    )
    token_a = body_a["subscription_url"].rsplit("/", 1)[-1]
    token_b = body_b["subscription_url"].rsplit("/", 1)[-1]
    assert token_a != token_b

    resp_a = await client.get(f"/sub/{token_a}")
    resp_b = await client.get(f"/sub/{token_b}")

    uuid_a = resp_a.text.split("@")[0].replace("vless://", "")
    uuid_b = resp_b.text.split("@")[0].replace("vless://", "")
    assert uuid_a != uuid_b
    assert uuid_a not in resp_b.text
    assert uuid_b not in resp_a.text


@pytest.mark.asyncio
async def test_wrong_user_cannot_manage_another_users_vless_device(
    client, internal_headers, sample_plan, db_session, fake_xray_agent_provider
):
    _, _, device_id = await _provision_vless_device(
        client, internal_headers, db_session, sample_plan, telegram_id=9010
    )
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 9011}, headers=internal_headers)
    other_headers = {**internal_headers, "X-Telegram-User-Id": "9011"}

    resp = await client.post(f"/api/v1/devices/{device_id}/disable", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_vless_servers_admin_crud(client, db_session):
    token = await _create_admin_token(client, db_session)
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post(
        "/api/v1/vless-servers",
        json={
            "name": "VLESS-DE-1",
            "country": "DE",
            "hostname": "vless-de1.example.com",
            "xray_agent_base_url": "https://vless-de1.example.com:8801",
            "port": 443,
            "reality_public_key": "PUBKEY",
            "reality_short_ids": [""],
            "sni": "www.example.com",
        },
        headers=headers,
    )
    assert create_resp.status_code == 201
    server_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "offline"

    list_resp = await client.get("/api/v1/vless-servers", headers=headers)
    assert list_resp.status_code == 200
    assert any(s["id"] == server_id for s in list_resp.json())

    update_resp = await client.patch(
        f"/api/v1/vless-servers/{server_id}",
        json={"status": "online", "sni": "updated.example.com"},
        headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "online"
    assert update_resp.json()["sni"] == "updated.example.com"

    delete_resp = await client.delete(f"/api/v1/vless-servers/{server_id}", headers=headers)
    assert delete_resp.status_code == 204

    list_after = await client.get("/api/v1/vless-servers", headers=headers)
    assert not any(s["id"] == server_id for s in list_after.json())


@pytest.mark.asyncio
async def test_vless_server_not_shown_in_wireguard_servers_list(
    client, internal_headers, db_session, fake_xray_agent_provider
):
    """GET /api/v1/servers (WireGuard's own listing — see bot/app/handlers/servers.py)
    must never surface a VLESS server: it has no protocol picker, so a mixed-in VLESS
    server would silently be treated as WireGuard by that flow."""
    await _create_vless_server(client, db_session)
    user_headers = {**internal_headers, "X-Telegram-User-Id": "9012"}
    await client.post("/api/v1/auth/telegram", json={"telegram_id": 9012}, headers=internal_headers)

    resp = await client.get("/api/v1/servers", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == []
