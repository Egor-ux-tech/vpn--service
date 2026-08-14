from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.common import get_backend, reply
from app.keyboards.menus import back_to_main

_AWAITING_SUPPORT_MESSAGE = "awaiting_support_message"


async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert context.user_data is not None
    context.user_data[_AWAITING_SUPPORT_MESSAGE] = True
    text = "<b>🆘 Поддержка</b>\n\nОпишите вашу проблему одним сообщением — мы ответим в этом чате."
    if query is not None:
        await query.answer()
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_to_main())
    elif update.message is not None:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=back_to_main())


async def support_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
    if not context.user_data.get(_AWAITING_SUPPORT_MESSAGE):
        return
    user = update.effective_user
    if user is None or update.message is None or update.message.text is None:
        return

    message_text = update.message.text.strip()
    context.user_data[_AWAITING_SUPPORT_MESSAGE] = False

    backend = get_backend(context)
    subject = message_text[:60]
    await backend.create_support_ticket(user.id, subject, message_text)

    await reply(
        update,
        "✅ Обращение создано. Мы ответим вам в этом чате в ближайшее время.",
        back_to_main(),
    )
