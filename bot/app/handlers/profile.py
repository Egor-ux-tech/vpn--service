from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.common import get_backend, reply
from app.keyboards.menus import back_to_main


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    profile = await backend.get_me(user.id)

    lines = [
        "<b>👤 Профиль</b>",
        "",
        f"ID: <code>{profile['telegram_id']}</code>",
        f"Username: @{profile['username']}" if profile.get("username") else "Username: —",
        f"Статус аккаунта: {profile['status']}",
    ]
    await reply(update, "\n".join(lines), back_to_main())
