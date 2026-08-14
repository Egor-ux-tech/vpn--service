"""Drives the full "connect to VPN" journey through real backend + vpn-agent processes,
via the bot's own BackendClient. See tests/README.md and tests/conftest.py.
"""

import hashlib
import hmac
import time
from typing import Any

import httpx
import orjson
import pytest

# Duplicated from conftest.py rather than imported: this top-level `tests/` directory sits
# alongside per-service `backend/tests`, `bot/tests`, `vpn/tests` packages of the same
# name, and pytest fixtures from conftest.py are auto-injected without an import — so
# `import tests.conftest` here would risk resolving to the wrong same-named package
# depending on which service's venv/cwd this suite is invoked from.
ADMIN_SECRET = "e2e-admin-bootstrap-secret"
PAYMENT_WEBHOOK_SECRET = "e2e-payment-webhook-secret"
VPN_AGENT_SHARED_SECRET = "e2e-vpn-agent-secret"

TELEGRAM_ID = 991234567


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_full_connect_to_vpn_journey(
    backend_process: str, vpn_agent_process: str, bot_client_module: Any
) -> None:
    backend_url = backend_process
    vpn_agent_url = vpn_agent_process
    settings_module = __import__("app.core.config", fromlist=["BotSettings"])
    bot_settings = settings_module.BotSettings(
        backend_api_base_url=backend_url,
        internal_service_token="e2e-internal-token",
        telegram_bot_token="123:test",
    )
    bot_client = bot_client_module(bot_settings)
    admin_http = httpx.AsyncClient(base_url=backend_url, timeout=10.0)

    try:
        # 1. Bootstrap the first admin account.
        resp = await admin_http.post(
            "/api/v1/auth/admin/bootstrap",
            json={
                "secret": ADMIN_SECRET,
                "email": "e2e-admin@example.com",
                "password": "e2e-admin-password",
            },
        )
        assert resp.status_code == 201
        admin_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        # 2. Admin creates a plan.
        resp = await admin_http.post(
            "/api/v1/plans",
            json={
                "name": "E2E Plan",
                "slug": "e2e-plan",
                "price": "199.00",
                "duration_days": 30,
                "max_devices": 3,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        plan_id = resp.json()["id"]

        # 3. Admin registers the VPN server (pointing at the real, live vpn-agent) and
        # brings it online.
        resp = await admin_http.post(
            "/api/v1/servers",
            json={
                "name": "E2E Server",
                "country": "NL",
                "hostname": "localhost",
                "agent_base_url": vpn_agent_url,
                "public_key": "SERVERPUBKEYE2E",
                "endpoint": "localhost:51820",
                "internal_network": "10.77.0.0/24",
                "capacity": 10,
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        server_id = resp.json()["id"]
        resp = await admin_http.patch(
            f"/api/v1/servers/{server_id}", json={"status": "online"}, headers=admin_headers
        )
        assert resp.status_code == 200

        # 4. Telegram user authenticates, exactly as the bot does on /start.
        user = await bot_client.authenticate(
            telegram_id=TELEGRAM_ID, username="e2e_user", first_name="E2E", last_name=None
        )
        assert user["telegram_id"] == TELEGRAM_ID

        # 5. User initiates a payment for the plan.
        payment = await bot_client.create_payment(TELEGRAM_ID, plan_id)
        assert payment["status"] == "pending"

        # 6. The payment provider confirms via webhook (idempotent, signature-verified) —
        # the mock provider encodes its own external id in the checkout URL it handed back.
        external_id = payment["checkout_url"].rsplit("/", 1)[-1]
        webhook_body = orjson.dumps(
            {
                "external_payment_id": external_id,
                "status": "succeeded",
                "amount": "199.00",
                "currency": "RUB",
            }
        )
        resp = await admin_http.post(
            "/api/v1/payments/webhook",
            content=webhook_body,
            headers={"X-Signature": _sign(webhook_body, PAYMENT_WEBHOOK_SECRET)},
        )
        assert resp.status_code == 200

        # 7. Subscription is now active.
        subscription = await bot_client.get_active_subscription(TELEGRAM_ID)
        assert subscription is not None
        assert subscription["status"] == "active"

        # 8. User provisions a device — backend allocates an IP, calls the real vpn-agent
        # over signed HTTP, gets back a keypair, and returns a ready-to-use WireGuard config.
        result = await bot_client.create_device(TELEGRAM_ID, "E2E Phone")
        device = result["device"]
        assert device["status"] == "active"
        assert "PrivateKey" in result["config_text"]
        assert "AllowedIPs" in result["config_text"]
        assert result["qr_code_base64"]

        # 9. Independently verify the peer exists on the vpn-agent — not through the
        # backend's own reporting, but a direct query to the agent itself.
        async with httpx.AsyncClient(base_url=vpn_agent_url, timeout=10.0) as agent_http:
            headers = {
                "X-Signature": _sign(b"", VPN_AGENT_SHARED_SECRET),
                "X-Timestamp": str(int(time.time())),
            }
            status_resp = await agent_http.get(
                "/peers/status", params={"public_key": device["public_key"]}, headers=headers
            )
            assert status_resp.status_code == 200
            assert status_resp.json()["status"] == "active"

        # 10. Disabling the device removes the peer from the live interface (but keeps the
        # record — see PeerReconciler.disable_peer).
        disabled = await bot_client.disable_device(TELEGRAM_ID, device["id"])
        assert disabled["status"] == "disabled"
        async with httpx.AsyncClient(base_url=vpn_agent_url, timeout=10.0) as agent_http:
            headers = {
                "X-Signature": _sign(b"", VPN_AGENT_SHARED_SECRET),
                "X-Timestamp": str(int(time.time())),
            }
            status_resp = await agent_http.get(
                "/peers/status", params={"public_key": device["public_key"]}, headers=headers
            )
            assert status_resp.json()["status"] == "disabled"

        # 11. Revoking tears the device down entirely.
        revoked = await bot_client.revoke_device(TELEGRAM_ID, device["id"])
        assert revoked["status"] == "revoked"
    finally:
        await bot_client.aclose()
        await admin_http.aclose()
