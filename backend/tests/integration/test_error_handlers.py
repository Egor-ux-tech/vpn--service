"""Proves the generic 500 handler (app.core.errors.handle_unexpected_error) never leaks
exception internals to the client, regardless of what actually broke — the one thing
standing between "some repository call threw an unexpected error" and an attacker learning
implementation details (stack traces, internal messages, variable values) from the
response body.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.deps import get_user_service


class _ExplodingUserService:
    """Stands in for UserService: raises before doing anything, from inside a real request
    handled by the real app/middleware/exception-handler stack — not a synthetic call to
    the handler function in isolation."""

    async def get_or_create_from_telegram(self, payload):
        raise RuntimeError("boom: super-secret-internal-detail 12345")


@pytest.fixture
def exploding_user_service(app):
    app.dependency_overrides[get_user_service] = lambda: _ExplodingUserService()
    yield
    del app.dependency_overrides[get_user_service]


@pytest_asyncio.fixture
async def client_over_the_wire(app) -> AsyncGenerator[AsyncClient, None]:
    """Like the shared `client` fixture, but with raise_app_exceptions=False.

    Starlette's ServerErrorMiddleware sends the exception handler's response to the client
    and *then* re-raises the original exception — deliberately, so it still reaches
    whatever's running the ASGI app for process-level logging (uvicorn logs it to stderr in
    production; here it's what feeds structlog's exc_info). httpx's ASGITransport defaults
    to propagating that re-raised exception into the calling test, which is right for every
    other test (an unexpected exception should fail loudly) but wrong for *this* one, whose
    entire point is to check what the response looks like after that has already happened.
    A real HTTP client never sees the re-raise at all — only the response bytes already
    sent — so this is what actually matches production behavior.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_unhandled_exception_returns_generic_500_body(
    client_over_the_wire, internal_headers, exploding_user_service
):
    resp = await client_over_the_wire.post(
        "/api/v1/auth/telegram", json={"telegram_id": 424242}, headers=internal_headers
    )

    assert resp.status_code == 500
    assert resp.headers["X-Error-Code"] == "internal_error"

    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Internal server error"
    assert body["error"]["details"] is None

    # The real exception message/type must never reach the client, in any field.
    raw = resp.text
    assert "boom" not in raw
    assert "super-secret-internal-detail" not in raw
    assert "RuntimeError" not in raw
    assert "Traceback" not in raw


@pytest.mark.asyncio
async def test_unhandled_exception_response_includes_request_id_for_support_correlation(
    client_over_the_wire, internal_headers, exploding_user_service
):
    """The client gets nothing about *what* broke, but should still get a request_id it
    can hand to support — the correlation path between an opaque client-facing error and
    the detailed server-side log (which does capture exc_info) runs through this field."""
    resp = await client_over_the_wire.post(
        "/api/v1/auth/telegram", json={"telegram_id": 424243}, headers=internal_headers
    )
    assert resp.json()["error"]["request_id"] != "-"
