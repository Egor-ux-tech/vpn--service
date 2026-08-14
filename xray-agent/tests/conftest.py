import os

os.environ.setdefault("STATE_DB_PATH", ":memory:")
os.environ.setdefault("APPLY_TO_LIVE_XRAY", "true")
os.environ.setdefault("XRAY_AGENT_SHARED_SECRET", "test-shared-secret")
os.environ.setdefault("XRAY_INBOUND_TAG", "vless-reality-in")

import hashlib
import hmac
import time

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.state.user_store import UserStore
from app.xray.reconciler import UserReconciler
from tests.fakes import FakeXrayHandlerClient


def sign(body: bytes) -> dict[str, str]:
    settings = get_settings()
    signature = hmac.new(
        settings.xray_agent_shared_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Signature": signature,
        "X-Timestamp": str(int(time.time())),
        # FastAPI/Starlette needs this to attempt JSON body parsing at all — the real
        # caller (backend's XrayAgentProvider) always sets it.
        "Content-Type": "application/json",
    }


@pytest_asyncio.fixture
async def fake_handler_client() -> FakeXrayHandlerClient:
    return FakeXrayHandlerClient()


@pytest_asyncio.fixture
async def reconciler(fake_handler_client: FakeXrayHandlerClient) -> UserReconciler:
    settings = get_settings()
    store = UserStore(":memory:")
    return UserReconciler(fake_handler_client, store, settings.xray_inbound_tag, True)


@pytest_asyncio.fixture
async def app(reconciler: UserReconciler):
    from app.main import create_app

    fastapi_app = create_app()
    fastapi_app.state.reconciler = reconciler
    yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
