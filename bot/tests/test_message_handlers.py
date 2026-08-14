"""Verifies each free-text handler only acts on its own user_data flag and otherwise
no-ops — this is what makes it safe to register all three in separate PTB handler groups
(see app/main.py) so a support message never gets mistaken for a device name, etc."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers.devices import _AWAITING_DEVICE_NAME, device_name_message_handler
from app.handlers.smart_vpn import _AWAITING_CUSTOM_DOMAIN, custom_domain_message_handler
from app.handlers.support import _AWAITING_SUPPORT_MESSAGE, support_message_handler


def _make_update(text: str = "hello"):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    user = SimpleNamespace(id=42)
    return SimpleNamespace(message=message, effective_user=user, callback_query=None)


def _make_context(user_data: dict, backend):
    application = SimpleNamespace(bot_data={"backend_client": backend})
    return SimpleNamespace(user_data=user_data, application=application)


@pytest.mark.asyncio
async def test_device_name_handler_ignores_message_when_flag_unset():
    backend = AsyncMock()
    update = _make_update("iPhone")
    context = _make_context({}, backend)

    await device_name_message_handler(update, context)

    backend.create_device.assert_not_called()


@pytest.mark.asyncio
async def test_device_name_handler_creates_device_when_flag_set():
    backend = AsyncMock()
    backend.create_device.return_value = {
        "device": {"name": "iPhone"},
        "config_text": "[Interface]\n",
        "qr_code_base64": "aGVsbG8=",
    }
    update = _make_update("iPhone")
    update.effective_chat = SimpleNamespace(send_photo=AsyncMock(), send_document=AsyncMock())
    context = _make_context({_AWAITING_DEVICE_NAME: True}, backend)

    await device_name_message_handler(update, context)

    backend.create_device.assert_awaited_once_with(42, "iPhone", None, "wireguard")
    assert context.user_data[_AWAITING_DEVICE_NAME] is False


@pytest.mark.asyncio
async def test_custom_domain_handler_ignores_when_flag_unset():
    backend = AsyncMock()
    update = _make_update("example.com")
    context = _make_context({}, backend)

    await custom_domain_message_handler(update, context)

    backend.add_custom_domain.assert_not_called()


@pytest.mark.asyncio
async def test_custom_domain_handler_adds_domain_when_flag_set():
    backend = AsyncMock()
    update = _make_update("Example.COM")
    context = _make_context({_AWAITING_CUSTOM_DOMAIN: True}, backend)

    await custom_domain_message_handler(update, context)

    backend.add_custom_domain.assert_awaited_once_with(42, "example.com")


@pytest.mark.asyncio
async def test_support_handler_ignores_when_flag_unset():
    backend = AsyncMock()
    update = _make_update("my vpn is broken")
    context = _make_context({}, backend)

    await support_message_handler(update, context)

    backend.create_support_ticket.assert_not_called()


@pytest.mark.asyncio
async def test_support_handler_creates_ticket_when_flag_set():
    backend = AsyncMock()
    update = _make_update("my vpn is broken")
    context = _make_context({_AWAITING_SUPPORT_MESSAGE: True}, backend)

    await support_message_handler(update, context)

    backend.create_support_ticket.assert_awaited_once()


@pytest.mark.asyncio
async def test_only_the_matching_flag_triggers_its_handler():
    """Simulates all three handlers running in sequence (as PTB would across groups 1/2/3)
    for a single incoming message — only the one whose flag is set should call the backend."""
    backend = AsyncMock()
    update = _make_update("some text")
    context = _make_context({_AWAITING_SUPPORT_MESSAGE: True}, backend)

    await device_name_message_handler(update, context)
    await custom_domain_message_handler(update, context)
    await support_message_handler(update, context)

    backend.create_device.assert_not_called()
    backend.add_custom_domain.assert_not_called()
    backend.create_support_ticket.assert_awaited_once()
