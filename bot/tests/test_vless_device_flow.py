"""VLESS-specific bot behavior: the protocol-choice step ahead of device naming, VLESS
config delivery (no QR/file — only the subscription link), and that device-management
actions correctly differ per protocol (no "reissue" button for VLESS — see
DeviceService.reissue's explicit rejection for protocol=vless).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.handlers.devices import (
    _AWAITING_DEVICE_NAME,
    _PENDING_PROTOCOL,
    _PENDING_SERVER_ID,
    _send_device_config,
    device_name_message_handler,
    device_new_callback,
    device_new_protocol_callback,
)
from app.keyboards.menus import device_manage_keyboard, protocol_choice_keyboard


def _make_callback_update(data: str):
    query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42))


def _make_context(user_data: dict | None = None):
    return SimpleNamespace(user_data=user_data if user_data is not None else {}, application=None)


@pytest.mark.asyncio
async def test_device_new_bare_shows_protocol_choice_not_name_prompt():
    update = _make_callback_update("device:new")
    context = _make_context()

    await device_new_callback(update, context)

    assert context.user_data.get(_AWAITING_DEVICE_NAME) is not True
    update.callback_query.edit_message_text.assert_awaited_once()
    _text, kwargs = update.callback_query.edit_message_text.call_args
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_device_new_with_server_id_skips_protocol_choice_defaults_wireguard():
    """Picking a server from the "Серверы" list is always WireGuard — that flow has no
    VLESS-server picker (see VPNServerService.list()'s docstring) — so it must behave
    exactly as it did before VLESS existed."""
    update = _make_callback_update("device:new:7")
    context = _make_context()

    await device_new_callback(update, context)

    assert context.user_data[_AWAITING_DEVICE_NAME] is True
    assert context.user_data[_PENDING_SERVER_ID] == 7
    assert context.user_data[_PENDING_PROTOCOL] == "wireguard"


@pytest.mark.asyncio
async def test_protocol_choice_callback_sets_pending_protocol_and_prompts_name():
    update = _make_callback_update("device:new:proto:vless")
    context = _make_context()

    await device_new_protocol_callback(update, context)

    assert context.user_data[_AWAITING_DEVICE_NAME] is True
    assert context.user_data[_PENDING_SERVER_ID] is None
    assert context.user_data[_PENDING_PROTOCOL] == "vless"
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_device_name_handler_forwards_chosen_protocol_to_backend():
    backend = AsyncMock()
    backend.create_device.return_value = {
        "device": {"name": "Phone", "protocol": "vless"},
        "config_text": None,
        "qr_code_base64": None,
        "subscription_url": None,
        "subscription_qr_code_base64": None,
    }
    message = SimpleNamespace(text="Phone", reply_text=AsyncMock())
    chat = SimpleNamespace(send_message=AsyncMock())
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=42),
        effective_chat=chat,
        callback_query=None,
    )
    application = SimpleNamespace(bot_data={"backend_client": backend})
    context = SimpleNamespace(
        user_data={_AWAITING_DEVICE_NAME: True, _PENDING_PROTOCOL: "vless"},
        application=application,
    )

    await device_name_message_handler(update, context)

    backend.create_device.assert_awaited_once_with(42, "Phone", None, "vless")


@pytest.mark.asyncio
async def test_send_device_config_sends_text_only_for_vless_no_qr_or_file():
    chat = SimpleNamespace(
        send_photo=AsyncMock(), send_document=AsyncMock(), send_message=AsyncMock()
    )
    update = SimpleNamespace(effective_chat=chat)
    result = {
        "device": {"name": "Phone", "protocol": "vless"},
        "config_text": None,
        "qr_code_base64": None,
        "subscription_url": None,
        "subscription_qr_code_base64": None,
    }

    await _send_device_config(update, result)

    chat.send_photo.assert_not_awaited()
    chat.send_document.assert_not_awaited()
    chat.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_device_config_sends_qr_and_file_for_wireguard():
    chat = SimpleNamespace(
        send_photo=AsyncMock(), send_document=AsyncMock(), send_message=AsyncMock()
    )
    update = SimpleNamespace(effective_chat=chat)
    result = {
        "device": {"name": "Laptop", "protocol": "wireguard"},
        "config_text": "[Interface]\nPrivateKey = X\n",
        "qr_code_base64": "aGVsbG8=",
        "subscription_url": None,
        "subscription_qr_code_base64": None,
    }

    await _send_device_config(update, result)

    chat.send_photo.assert_awaited_once()
    chat.send_document.assert_awaited_once()


def test_device_manage_keyboard_hides_reissue_for_vless():
    device = {"id": 1, "status": "active", "protocol": "vless"}
    markup = device_manage_keyboard(device)
    all_labels = [button.text for row in markup.inline_keyboard for button in row]
    assert not any("Переиздать" in label for label in all_labels)
    assert any("Ссылка подписки" in label for label in all_labels)


def test_device_manage_keyboard_shows_reissue_for_wireguard():
    device = {"id": 1, "status": "active", "protocol": "wireguard"}
    markup = device_manage_keyboard(device)
    all_labels = [button.text for row in markup.inline_keyboard for button in row]
    assert any("Переиздать" in label for label in all_labels)


def test_protocol_choice_keyboard_has_both_options():
    markup = protocol_choice_keyboard()
    all_data = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "device:new:proto:wireguard" in all_data
    assert "device:new:proto:vless" in all_data
