import httpx
import pytest

from app.core.config import BotSettings
from app.services.backend_client import BackendClient, BackendError


def _client_with_transport(handler) -> BackendClient:
    settings = BotSettings(backend_api_base_url="http://backend.local")
    client = BackendClient(settings)
    client._client = httpx.AsyncClient(
        base_url="http://backend.local", transport=httpx.MockTransport(handler)
    )
    return client


@pytest.mark.asyncio
async def test_get_subscription_link_returns_metadata_when_present():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/devices/7/subscription-link"
        return httpx.Response(
            200,
            json={
                "device_id": 7,
                "status": "active",
                "token_prefix": "abc12345",
                "created_at": "2026-08-14T00:00:00Z",
                "rotated_at": None,
                "revoked_at": None,
                "last_accessed_at": None,
            },
        )

    client = _client_with_transport(handler)
    link = await client.get_subscription_link(42, 7)

    assert link is not None
    assert link["status"] == "active"
    assert link["token_prefix"] == "abc12345"


@pytest.mark.asyncio
async def test_get_subscription_link_returns_none_when_backend_says_not_found():
    """The distinguishing feature of this call: a 404 with error_code
    subscription_link_not_found means "no link yet, this is normal" — not an error the
    caller should have to catch. Any other error still propagates as BackendError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "subscription_link_not_found",
                    "message": "No subscription link exists for this device yet",
                }
            },
        )

    client = _client_with_transport(handler)
    link = await client.get_subscription_link(42, 7)

    assert link is None


@pytest.mark.asyncio
async def test_get_subscription_link_reraises_other_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"code": "device_not_found", "message": "Device not found"}}
        )

    client = _client_with_transport(handler)

    with pytest.raises(BackendError) as exc_info:
        await client.get_subscription_link(42, 7)
    assert exc_info.value.error_code == "device_not_found"


@pytest.mark.asyncio
async def test_create_or_rotate_subscription_link_posts_and_returns_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["headers"] = request.headers
        return httpx.Response(
            201,
            json={
                "link": {"device_id": 7, "status": "active", "token_prefix": "xyz98765"},
                "subscription_url": "http://backend.local/sub/xyz98765rest-of-token",
                "qr_code_base64": "aGVsbG8=",
            },
        )

    client = _client_with_transport(handler)
    result = await client.create_or_rotate_subscription_link(42, 7)

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/devices/7/subscription-link"
    assert captured["headers"]["x-telegram-user-id"] == "42"
    assert result["subscription_url"].endswith("xyz98765rest-of-token")
    assert result["qr_code_base64"] == "aGVsbG8="
