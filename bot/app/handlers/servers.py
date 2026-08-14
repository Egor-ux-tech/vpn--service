from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.common import get_backend, reply
from app.keyboards.menus import servers_keyboard


async def servers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    servers = await backend.list_servers(user.id)

    if not servers:
        await reply(update, "Пока нет доступных серверов. Загляните позже.", servers_keyboard([]))
        return

    lines = ["<b>🌍 Серверы</b>", "", "Выберите сервер, чтобы подключить новое устройство:"]
    await reply(update, "\n".join(lines), servers_keyboard(servers))
