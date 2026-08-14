import os

os.environ.setdefault("STATE_DB_PATH", ":memory:")
os.environ.setdefault("APPLY_TO_LIVE_INTERFACE", "false")
os.environ.setdefault("VPN_AGENT_SHARED_SECRET", "test-shared-secret")

import hashlib
import hmac
import time

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings


def sign(body: bytes) -> dict[str, str]:
    settings = get_settings()
    signature = hmac.new(
        settings.vpn_agent_shared_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Signature": signature,
        "X-Timestamp": str(int(time.time())),
        # The real caller (backend's WireGuardProvider) always sets this; current
        # Starlette/FastAPI requires it to attempt JSON body parsing at all (older versions
        # were lenient), so the test client must match real client behavior here.
        "Content-Type": "application/json",
    }


@pytest_asyncio.fixture
async def app():
    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
