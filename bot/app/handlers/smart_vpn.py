from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.common import get_backend, reply
from app.keyboards.menus import smart_vpn_categories_keyboard, smart_vpn_mode_keyboard

_AWAITING_CUSTOM_DOMAIN = "awaiting_custom_domain"


async def smart_vpn_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    settings = await backend.get_routing_settings(user.id)

    lines = [
        "<b>🧭 Smart VPN</b>",
        "",
        "FULL VPN — весь трафик идёт через VPN.",
        "SMART VPN — вы выбираете, какие категории/домены идут через VPN, а какие напрямую.",
        "",
        f"Текущий режим: <b>{'SMART VPN' if settings['mode'] == 'smart_vpn' else 'FULL VPN'}</b>",
    ]
    await reply(update, "\n".join(lines), smart_vpn_mode_keyboard(settings["mode"]))


async def smart_vpn_set_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    mode = query.data.split(":", 2)[-1]
    backend = get_backend(context)
    await backend.set_routing_mode(user.id, mode)
    await query.answer("Режим обновлён")
    await smart_vpn_menu_callback(update, context)


async def smart_vpn_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    settings = await backend.get_routing_settings(user.id)
    enabled_ids = set(settings["enabled_category_ids"])

    text = "<b>🗂️ Категории Smart VPN</b>\n\nОтметьте, что должно идти через VPN:"
    await reply(update, text, smart_vpn_categories_keyboard(settings["categories"], enabled_ids))


async def smart_vpn_toggle_category_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    category_id = int(query.data.split(":")[-1])
    backend = get_backend(context)

    settings = await backend.get_routing_settings(user.id)
    currently_enabled = category_id in set(settings["enabled_category_ids"])
    await backend.set_category_preference(user.id, category_id, not currently_enabled)

    await query.answer()
    await smart_vpn_categories_callback(update, context)


async def smart_vpn_add_domain_prompt_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return
    assert context.user_data is not None
    context.user_data[_AWAITING_CUSTOM_DOMAIN] = True
    await query.answer()
    await query.edit_message_text(
        "Введите домен, который должен идти через VPN (например: example.com):"
    )


async def custom_domain_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert context.user_data is not None
    if not context.user_data.get(_AWAITING_CUSTOM_DOMAIN):
        return
    user = update.effective_user
    if user is None or update.message is None or update.message.text is None:
        return

    domain = update.message.text.strip().lower()[:255]
    context.user_data[_AWAITING_CUSTOM_DOMAIN] = False

    backend = get_backend(context)
    await backend.add_custom_domain(user.id, domain)
    await update.message.reply_text(f"✅ Домен «{domain}» добавлен в Smart VPN.")
