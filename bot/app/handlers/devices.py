import base64
from io import BytesIO

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from app.core.logging import get_logger
from app.handlers.common import get_backend, reply
from app.keyboards.menus import device_manage_keyboard, devices_keyboard, main_menu
from app.services.backend_client import BackendError

logger = get_logger(__name__)

_AWAITING_DEVICE_NAME = "awaiting_device_name"
_PENDING_SERVER_ID = "pending_device_server_id"


async def devices_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    devices = await backend.list_devices(user.id)
    devices = [d for d in devices if d["status"] != "revoked"]

    if not devices:
        await reply(update, "У вас пока нет устройств.", devices_keyboard([]))
        return

    await reply(update, "<b>📱 Мои устройства</b>", devices_keyboard(devices))


async def device_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    device_id = int(query.data.split(":")[-1])
    backend = get_backend(context)
    devices = await backend.list_devices(user.id)
    device = next((d for d in devices if d["id"] == device_id), None)
    if device is None:
        await reply(update, "Устройство не найдено.", devices_keyboard([]))
        return

    status_label = {"active": "🟢 Активно", "disabled": "⏸️ Отключено"}.get(
        device["status"], device["status"]
    )
    lines = [
        f"<b>{device['name']}</b>",
        "",
        f"Статус: {status_label}",
        f"IP: <code>{device.get('assigned_ip') or '—'}</code>",
    ]
    await reply(update, "\n".join(lines), device_manage_keyboard(device))


async def device_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    parts = query.data.split(":")
    server_id = int(parts[2]) if len(parts) > 2 else None

    assert context.user_data is not None
    context.user_data[_AWAITING_DEVICE_NAME] = True
    context.user_data[_PENDING_SERVER_ID] = server_id

    await query.answer()
    await query.edit_message_text(
        "Введите название устройства (например: iPhone, MacBook, Домашний ПК):"
    )


async def device_name_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
    if not context.user_data.get(_AWAITING_DEVICE_NAME):
        return
    user = update.effective_user
    if user is None or update.message is None or update.message.text is None:
        return

    name = update.message.text.strip()[:64]
    context.user_data[_AWAITING_DEVICE_NAME] = False
    server_id = context.user_data.pop(_PENDING_SERVER_ID, None)

    backend = get_backend(context)
    try:
        result = await backend.create_device(user.id, name, server_id)
    except BackendError as exc:
        await update.message.reply_text(
            f"Не удалось создать устройство: {exc}", reply_markup=main_menu()
        )
        return

    await _send_device_config(update, result)


async def device_reissue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    device_id = int(query.data.split(":")[-1])
    backend = get_backend(context)
    await query.answer("Переиздаём конфигурацию...")

    try:
        result = await backend.reissue_device(user.id, device_id)
    except BackendError as exc:
        await query.edit_message_text(f"Не удалось переиздать конфигурацию: {exc}")
        return

    await _send_device_config(update, result)


async def device_disable_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_device(update, context, action="disable")


async def device_enable_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_device(update, context, action="enable")


async def device_revoke_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    device_id = int(query.data.split(":")[-1])
    backend = get_backend(context)
    await backend.revoke_device(user.id, device_id)
    await query.answer("Устройство удалено")
    await devices_list_callback(update, context)


async def _toggle_device(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, action: str
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    device_id = int(query.data.split(":")[-1])
    backend = get_backend(context)
    if action == "disable":
        await backend.disable_device(user.id, device_id)
    else:
        await backend.enable_device(user.id, device_id)
    await query.answer("Готово")
    await device_manage_callback(update, context)


async def _send_device_config(update: Update, result: dict) -> None:
    """Delivers the WireGuard config + QR code + instructions. `config_text` and the QR
    image both contain the device's private key — this function is the only place in the
    bot that ever sees that value, and it never logs it."""
    device_name = result["device"]["name"]
    qr_bytes = base64.b64decode(result["qr_code_base64"])

    chat = update.effective_chat
    if chat is None:
        return

    caption = (
        f"✅ Устройство «{device_name}» готово!\n\n"
        "Отсканируйте QR-код в приложении WireGuard, либо загрузите файл конфигурации "
        "ниже.\n\n"
        "<b>Как подключиться:</b>\n"
        "1. Установите приложение WireGuard (App Store / Google Play / wireguard.com)\n"
        "2. Нажмите «+» → «Сканировать QR-код» (или импортируйте файл)\n"
        "3. Включите туннель"
    )
    await chat.send_photo(photo=BytesIO(qr_bytes), caption=caption, parse_mode="HTML")

    config_file = InputFile(
        BytesIO(result["config_text"].encode("utf-8")), filename=f"{device_name}.conf"
    )
    await chat.send_document(document=config_file)
