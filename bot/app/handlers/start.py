from telegram import Update
from telegram.ext import ContextTypes

from app.core.logging import get_logger
from app.handlers.common import build_status_text, get_backend, reply
from app.keyboards.menus import main_menu

logger = get_logger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)

    await backend.authenticate(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    logger.info("user_started_bot", telegram_id=user.id)

    text = await build_status_text(backend, user.id)
    await reply(update, text, main_menu())


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    text = await build_status_text(backend, user.id)
    await reply(update, text, main_menu())
