from datetime import datetime

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.services.backend_client import BackendClient

STATUS_LABELS = {"active": "🟢 Активна", "expired": "🔴 Истекла", "cancelled": "⚪️ Отменена"}


def get_backend(context: ContextTypes.DEFAULT_TYPE) -> BackendClient:
    client = context.application.bot_data.get("backend_client")
    if client is None:
        raise RuntimeError("backend_client not initialized in bot_data")
    return client


async def reply(update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    """Edits the message in place when responding to a button tap, otherwise sends a new
    one — keeps the chat from filling up with a new message per click."""
    if update.callback_query is not None:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="HTML"
        )
    elif update.message is not None:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


def format_date(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return iso_str
    return dt.strftime("%d.%m.%Y")


async def build_status_text(backend: BackendClient, telegram_id: int) -> str:
    subscription = await backend.get_active_subscription(telegram_id)
    devices = await backend.list_devices(telegram_id)
    active_devices = [d for d in devices if d["status"] != "revoked"]

    lines = ["<b>🔐 Мой VPN</b>", ""]
    if subscription:
        status_label = STATUS_LABELS.get(subscription["status"], subscription["status"])
        lines.append(f"Статус: {status_label}")
        lines.append(f"План: {subscription['plan']['name']}")
        lines.append(f"До: {format_date(subscription.get('expires_at'))}")
        max_devices = subscription["plan"]["max_devices"]
        lines.append(f"Устройств: {len(active_devices)}/{max_devices}")
    else:
        lines.append("Статус: 🔴 Нет активной подписки")
        lines.append("Оформите подписку в разделе «Подписка», чтобы подключить устройство.")
    return "\n".join(lines)
