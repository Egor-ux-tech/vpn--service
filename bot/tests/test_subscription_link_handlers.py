"""Subscription-link Telegram delivery: sending the link+QR after provisioning, and the
view/rotate callbacks reachable from the device-management keyboard."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers.devices import (
    _send_device_config,
    device_subscription_link_rotate_callback,
    device_subscription_link_view_callback,
)


def _make_chat():
    return SimpleNamespace(
        send_photo=AsyncMock(), send_document=AsyncMock(), send_message=AsyncMock()
    )


def _make_callback_update(data: str, chat=None):
    query = SimpleNamespace(
        data=data,
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    user = SimpleNamespace(id=42)
    return SimpleNamespace(
        callback_query=query, effective_user=user, effective_chat=chat, message=None
    )


def _make_context(backend):
    application = SimpleNamespace(bot_data={"backend_client": backend})
    return SimpleNamespace(user_data={}, application=application)


@pytest.mark.asyncio
async def test_send_device_config_also_sends_subscription_link_when_present():
    chat = _make_chat()
    update = SimpleNamespace(effective_chat=chat)
    result = {
        "device": {"id": 7, "name": "iPhone"},
        "config_text": "[Interface]\nPrivateKey = X\n",
        "qr_code_base64": "aGVsbG8=",
        "subscription_url": "http://backend.local/sub/realtoken123",
        "subscription_qr_code_base64": "d29ybGQ=",
    }

    await _send_device_config(update, result)

    # Two photos: the WireGuard QR and the subscription-link QR.
    assert chat.send_photo.await_count == 2
    assert chat.send_document.await_count == 1
    # A follow-up management-keyboard message accompanies the subscription link.
    assert chat.send_message.await_count == 1

    subscription_caption = chat.send_photo.await_args_list[1].kwargs["caption"]
    assert "http://backend.local/sub/realtoken123" in subscription_caption


@pytest.mark.asyncio
async def test_send_device_config_skips_subscription_link_when_absent():
    """reissue() never populates subscription_url (see ProvisionedDevice's docstring in
    the backend) — the bot must not send a stale/misleading link message for it."""
    chat = _make_chat()
    update = SimpleNamespace(effective_chat=chat)
    result = {
        "device": {"id": 7, "name": "iPhone"},
        "config_text": "[Interface]\nPrivateKey = X\n",
        "qr_code_base64": "aGVsbG8=",
        "subscription_url": None,
        "subscription_qr_code_base64": None,
    }

    await _send_device_config(update, result)

    assert chat.send_photo.await_count == 1  # only the WireGuard QR
    assert chat.send_message.await_count == 0


@pytest.mark.asyncio
async def test_view_callback_shows_existing_link_metadata():
    backend = AsyncMock()
    backend.get_subscription_link.return_value = {
        "status": "active",
        "token_prefix": "abc12345",
        "created_at": "2026-08-14T00:00:00Z",
    }
    update = _make_callback_update("device:sublink:view:7")
    context = _make_context(backend)

    await device_subscription_link_view_callback(update, context)

    backend.get_subscription_link.assert_awaited_once_with(42, 7)
    update.callback_query.edit_message_text.assert_awaited_once()
    text = update.callback_query.edit_message_text.await_args.args[0]
    assert "abc12345" in text


@pytest.mark.asyncio
async def test_view_callback_handles_no_link_yet():
    backend = AsyncMock()
    backend.get_subscription_link.return_value = None
    update = _make_callback_update("device:sublink:view:7")
    context = _make_context(backend)

    await device_subscription_link_view_callback(update, context)

    text = update.callback_query.edit_message_text.await_args.args[0]
    assert "Обновить ссылку" in text or "ещё нет" in text.lower()


@pytest.mark.asyncio
async def test_rotate_callback_creates_link_and_sends_it():
    backend = AsyncMock()
    backend.create_or_rotate_subscription_link.return_value = {
        "link": {"status": "active"},
        "subscription_url": "http://backend.local/sub/freshtoken",
        "qr_code_base64": "cXI=",
    }
    chat = _make_chat()
    update = _make_callback_update("device:sublink:rotate:7", chat=chat)
    context = _make_context(backend)

    await device_subscription_link_rotate_callback(update, context)

    backend.create_or_rotate_subscription_link.assert_awaited_once_with(42, 7)
    chat.send_photo.assert_awaited_once()
    caption = chat.send_photo.await_args.kwargs["caption"]
    assert "http://backend.local/sub/freshtoken" in caption


@pytest.mark.asyncio
async def test_rotate_callback_reports_backend_error():
    from app.services.backend_client import BackendError

    backend = AsyncMock()
    backend.create_or_rotate_subscription_link.side_effect = BackendError(
        404, "device_not_found", "Device not found"
    )
    chat = _make_chat()
    update = _make_callback_update("device:sublink:rotate:7", chat=chat)
    context = _make_context(backend)

    await device_subscription_link_rotate_callback(update, context)

    update.callback_query.edit_message_text.assert_awaited_once()
    chat.send_photo.assert_not_awaited()
