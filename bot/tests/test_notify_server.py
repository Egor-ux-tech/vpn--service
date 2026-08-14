from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.config import BotSettings
from app.notify_server import create_notify_app


def _make_app(bot_send_message=None):
    settings = BotSettings(internal_service_token="test-internal-token")
    ptb_application = type("FakeApp", (), {})()
    ptb_application.bot = type("FakeBot", (), {})()
    ptb_application.bot.send_message = bot_send_message or AsyncMock()
    app = create_notify_app(ptb_application, settings)
    return app, ptb_application


def test_health_does_not_require_auth():
    app, _ = _make_app()
    client = TestClient(app)
    assert client.get("/health").status_code == 200


def test_notify_requires_internal_token():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.post("/notify", json={"telegram_id": 1, "message": "hi"})
    assert resp.status_code == 401


def test_notify_rejects_wrong_token():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.post(
        "/notify",
        json={"telegram_id": 1, "message": "hi"},
        headers={"X-Internal-Token": "wrong"},
    )
    assert resp.status_code == 401


def test_notify_sends_message_with_valid_token():
    send_message = AsyncMock()
    app, _ = _make_app(send_message)
    client = TestClient(app)

    resp = client.post(
        "/notify",
        json={"telegram_id": 42, "message": "Your subscription expired"},
        headers={"X-Internal-Token": "test-internal-token"},
    )

    assert resp.status_code == 204
    send_message.assert_awaited_once_with(chat_id=42, text="Your subscription expired")


def test_notify_swallows_telegram_errors_and_still_returns_204():
    from telegram.error import TelegramError

    send_message = AsyncMock(side_effect=TelegramError("bot was blocked by the user"))
    app, _ = _make_app(send_message)
    client = TestClient(app)

    resp = client.post(
        "/notify",
        json={"telegram_id": 42, "message": "hi"},
        headers={"X-Internal-Token": "test-internal-token"},
    )

    assert resp.status_code == 204
