import base64
from io import BytesIO

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from app.core.logging import get_logger
from app.handlers.common import format_date, get_backend, reply
from app.keyboards.menus import (
    device_manage_keyboard,
    devices_keyboard,
    main_menu,
    protocol_choice_keyboard,
    subscription_link_keyboard,
)
from app.services.backend_client import BackendError

logger = get_logger(__name__)

_AWAITING_DEVICE_NAME = "awaiting_device_name"
_PENDING_SERVER_ID = "pending_device_server_id"
_PENDING_PROTOCOL = "pending_device_protocol"
_PROTOCOL_LABELS = {"wireguard": "WireGuard", "vless": "VLESS"}


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
    protocol_label = _PROTOCOL_LABELS.get(device.get("protocol", "wireguard"), "WireGuard")
    lines = [
        f"<b>{device['name']}</b>",
        "",
        f"Статус: {status_label}",
        f"Протокол: {protocol_label}",
        f"IP: <code>{device.get('assigned_ip') or '—'}</code>",
    ]
    await reply(update, "\n".join(lines), device_manage_keyboard(device))


async def device_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point from the main menu's "🔌 Подключиться" button (bare "device:new") or
    from picking a specific WireGuard server in the "Серверы" list ("device:new:{id}").
    Only the bare form asks which protocol to use: a server picked from the "Серверы"
    list is always WireGuard (that flow predates VLESS and has no VLESS-server picker —
    see VPNServerService.list()'s docstring), so it skips straight to the name prompt
    exactly as before."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    parts = query.data.split(":")
    server_id = int(parts[2]) if len(parts) > 2 else None

    assert context.user_data is not None
    if server_id is not None:
        context.user_data[_AWAITING_DEVICE_NAME] = True
        context.user_data[_PENDING_SERVER_ID] = server_id
        context.user_data[_PENDING_PROTOCOL] = "wireguard"
        await query.answer()
        await query.edit_message_text(
            "Введите название устройства (например: iPhone, MacBook, Домашний ПК):"
        )
        return

    await query.answer()
    await query.edit_message_text(
        "Выберите протокол подключения:", reply_markup=protocol_choice_keyboard()
    )


async def device_new_protocol_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    protocol = query.data.split(":")[-1]

    assert context.user_data is not None
    context.user_data[_AWAITING_DEVICE_NAME] = True
    context.user_data[_PENDING_SERVER_ID] = None
    context.user_data[_PENDING_PROTOCOL] = protocol

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
    protocol = context.user_data.pop(_PENDING_PROTOCOL, "wireguard")

    backend = get_backend(context)
    try:
        result = await backend.create_device(user.id, name, server_id, protocol)
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
    """Delivers the device's config. For WireGuard: a QR code + downloadable .conf file
    (both contain the device's private key — this function is the only place in the bot
    that ever sees that value, and it never logs it). For VLESS, `config_text`/
    `qr_code_base64` are None — there is no separate downloadable artifact, only the
    subscription link section below (see ProvisionedDevice's docstring in
    device_service.py for why)."""
    device_name = result["device"]["name"]
    protocol = result["device"].get("protocol", "wireguard")

    chat = update.effective_chat
    if chat is None:
        return

    if protocol == "wireguard" and result.get("config_text") and result.get("qr_code_base64"):
        qr_bytes = base64.b64decode(result["qr_code_base64"])
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
    else:
        await chat.send_message(
            f"✅ Устройство «{device_name}» готово!\n\n"
            "Добавьте ссылку подписки ниже в приложение (например Happ), чтобы подключиться.",
            parse_mode="HTML",
        )

    # Only present when this result came from provisioning a brand-new device — reissue()
    # doesn't touch the subscription link, so there's nothing new to show there (see
    # ProvisionedDevice's docstring in device_service.py).
    if result.get("subscription_url"):
        await _send_subscription_link(
            update,
            device_id=result["device"]["id"],
            subscription_url=result["subscription_url"],
            qr_code_base64=result["subscription_qr_code_base64"],
        )


async def _send_subscription_link(
    update: Update, *, device_id: int, subscription_url: str, qr_code_base64: str
) -> None:
    """Delivers a subscription link + its QR code. Like _send_device_config, this is the
    only place in the bot that ever sees the plaintext link and never logs it — the
    backend only ever returns it once, at creation/rotation (see SubscriptionLinkService:
    only the link's hash is stored, so it cannot be re-shown later)."""
    chat = update.effective_chat
    if chat is None:
        return

    qr_bytes = base64.b64decode(qr_code_base64)
    caption = (
        "🔗 <b>Ссылка подписки готова</b>\n\n"
        f"<code>{subscription_url}</code>\n\n"
        "Добавьте её в приложение (например Happ) как подписку, либо отсканируйте "
        "QR-код ниже.\n\n"
        "⚠️ Ссылка показывается только сейчас. Она не сохраняется в открытом виде — "
        "если вы её потеряете, обновите её в меню устройства (старая ссылка перестанет "
        "работать)."
    )
    await chat.send_photo(photo=BytesIO(qr_bytes), caption=caption, parse_mode="HTML")
    await chat.send_message(
        "Управление ссылкой:", reply_markup=subscription_link_keyboard(device_id)
    )


async def device_subscription_link_view_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    device_id = int(query.data.split(":")[-1])
    backend = get_backend(context)
    link = await backend.get_subscription_link(user.id, device_id)

    if link is None:
        text = (
            "<b>🔗 Ссылка подписки</b>\n\n"
            "Для этого устройства пока нет ссылки подписки.\n"
            "Нажмите «Обновить ссылку», чтобы создать её."
        )
    else:
        status_label = "🟢 Активна" if link["status"] == "active" else "🔴 Отозвана"
        text = (
            "<b>🔗 Ссылка подписки</b>\n\n"
            f"Статус: {status_label}\n"
            f"Начало: <code>{link['token_prefix']}...</code>\n"
            f"Создана: {format_date(link['created_at'])}\n\n"
            "Сама ссылка показывается только один раз — сразу после создания или "
            "обновления. Чтобы получить рабочую ссылку снова, нажмите «Обновить ссылку» "
            "(старая перестанет работать)."
        )
    await reply(update, text, subscription_link_keyboard(device_id))


async def device_subscription_link_rotate_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    device_id = int(query.data.split(":")[-1])
    backend = get_backend(context)
    await query.answer("Обновляем ссылку...")

    try:
        result = await backend.create_or_rotate_subscription_link(user.id, device_id)
    except BackendError as exc:
        await query.edit_message_text(f"Не удалось обновить ссылку: {exc}")
        return

    await _send_subscription_link(
        update,
        device_id=device_id,
        subscription_url=result["subscription_url"],
        qr_code_base64=result["qr_code_base64"],
    )
