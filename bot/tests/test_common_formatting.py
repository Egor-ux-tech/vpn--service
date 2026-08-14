import pytest

from app.handlers.common import build_status_text, format_date


def test_format_date_handles_iso_with_z_suffix():
    assert format_date("2026-09-15T10:00:00Z") == "15.09.2026"


def test_format_date_handles_missing_value():
    assert format_date(None) == "—"


def test_format_date_handles_garbage_gracefully():
    assert format_date("not-a-date") == "not-a-date"


class _FakeBackend:
    def __init__(self, subscription, devices):
        self._subscription = subscription
        self._devices = devices

    async def get_active_subscription(self, telegram_id: int):
        return self._subscription

    async def list_devices(self, telegram_id: int):
        return self._devices


@pytest.mark.asyncio
async def test_status_text_shows_no_subscription_message():
    backend = _FakeBackend(subscription=None, devices=[])
    text = await build_status_text(backend, telegram_id=1)
    assert "Нет активной подписки" in text


@pytest.mark.asyncio
async def test_status_text_shows_device_count_excluding_revoked():
    subscription = {
        "status": "active",
        "plan": {"name": "Premium", "max_devices": 5},
        "expires_at": "2026-09-15T10:00:00Z",
    }
    devices = [
        {"status": "active"},
        {"status": "active"},
        {"status": "revoked"},
    ]
    backend = _FakeBackend(subscription=subscription, devices=devices)
    text = await build_status_text(backend, telegram_id=1)

    assert "2/5" in text
    assert "Premium" in text
