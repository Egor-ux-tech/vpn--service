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
async def test_authenticate_sends_internal_token_and_telegram_headers():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(200, json={"id": 1, "telegram_id": 42, "status": "active"})

    client = _client_with_transport(handler)
    result = await client.authenticate(
        telegram_id=42, username="bob", first_name="Bob", last_name=None
    )

    assert result["telegram_id"] == 42
    assert captured["headers"]["x-internal-token"] == "test-internal-token"


@pytest.mark.asyncio
async def test_get_me_sends_telegram_user_id_header():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        return httpx.Response(200, json={"telegram_id": 42})

    client = _client_with_transport(handler)
    await client.get_me(42)

    assert captured["headers"]["x-telegram-user-id"] == "42"


@pytest.mark.asyncio
async def test_error_response_raises_backend_error_with_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409, json={"error": {"code": "device_limit_reached", "message": "Limit reached"}}
        )

    client = _client_with_transport(handler)

    with pytest.raises(BackendError) as exc_info:
        await client.create_device(42, "Phone")

    assert exc_info.value.status_code == 409
    assert exc_info.value.error_code == "device_limit_reached"


@pytest.mark.asyncio
async def test_no_content_response_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = _client_with_transport(handler)
    result = await client.revoke_device(42, 1)

    assert result is None


@pytest.mark.asyncio
async def test_get_active_subscription_returns_null_body_as_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=None)

    client = _client_with_transport(handler)
    result = await client.get_active_subscription(42)

    assert result is None
