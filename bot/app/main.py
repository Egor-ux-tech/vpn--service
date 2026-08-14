import asyncio

import uvicorn
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import BOT_ERRORS_TOTAL
from app.handlers.commands import (
    devices_command,
    profile_command,
    servers_command,
    smart_vpn_command,
    subscription_command,
    support_command,
    vpn_command,
)
from app.handlers.devices import (
    device_disable_callback,
    device_enable_callback,
    device_manage_callback,
    device_name_message_handler,
    device_new_callback,
    device_reissue_callback,
    device_revoke_callback,
    devices_list_callback,
)
from app.handlers.profile import profile_callback
from app.handlers.servers import servers_callback
from app.handlers.smart_vpn import (
    custom_domain_message_handler,
    smart_vpn_add_domain_prompt_callback,
    smart_vpn_categories_callback,
    smart_vpn_menu_callback,
    smart_vpn_set_mode_callback,
    smart_vpn_toggle_category_callback,
)
from app.handlers.start import main_menu_callback, start_command
from app.handlers.subscription import buy_plan_callback, subscription_menu_callback
from app.handlers.support import support_menu_callback, support_message_handler
from app.notify_server import create_notify_app
from app.services.backend_client import BackendClient

logger = get_logger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    BOT_ERRORS_TOTAL.inc()
    logger.error("bot_unhandled_error", error=str(context.error), update=repr(update))
    if isinstance(update, Update) and update.effective_message is not None:
        await update.effective_message.reply_text(
            "Что-то пошло не так. Попробуйте ещё раз или напишите в поддержку /support."
        )


def build_application() -> Application:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["backend_client"] = BackendClient(settings)

    # Slash commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("vpn", vpn_command))
    application.add_handler(CommandHandler("servers", servers_command))
    application.add_handler(CommandHandler("subscription", subscription_command))
    application.add_handler(CommandHandler("devices", devices_command))
    application.add_handler(CommandHandler("support", support_command))
    application.add_handler(CommandHandler("smartvpn", smart_vpn_command))

    # Main menu
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^menu:main$"))
    application.add_handler(CallbackQueryHandler(profile_callback, pattern="^menu:profile$"))
    application.add_handler(CallbackQueryHandler(servers_callback, pattern="^menu:servers$"))
    application.add_handler(
        CallbackQueryHandler(subscription_menu_callback, pattern="^menu:subscription$")
    )
    application.add_handler(CallbackQueryHandler(devices_list_callback, pattern="^menu:devices$"))
    application.add_handler(CallbackQueryHandler(smart_vpn_menu_callback, pattern="^menu:smart$"))
    application.add_handler(CallbackQueryHandler(support_menu_callback, pattern="^menu:support$"))

    # Devices
    application.add_handler(CallbackQueryHandler(device_new_callback, pattern="^device:new"))
    application.add_handler(CallbackQueryHandler(device_manage_callback, pattern="^device:manage:"))
    application.add_handler(
        CallbackQueryHandler(device_reissue_callback, pattern="^device:reissue:")
    )
    application.add_handler(
        CallbackQueryHandler(device_disable_callback, pattern="^device:disable:")
    )
    application.add_handler(CallbackQueryHandler(device_enable_callback, pattern="^device:enable:"))
    application.add_handler(CallbackQueryHandler(device_revoke_callback, pattern="^device:revoke:"))

    # Subscription / payments
    application.add_handler(CallbackQueryHandler(buy_plan_callback, pattern="^plan:buy:"))

    # Smart VPN
    application.add_handler(
        CallbackQueryHandler(smart_vpn_set_mode_callback, pattern="^smart:mode:")
    )
    application.add_handler(
        CallbackQueryHandler(smart_vpn_categories_callback, pattern="^smart:categories$")
    )
    application.add_handler(
        CallbackQueryHandler(smart_vpn_toggle_category_callback, pattern="^smart:cat:")
    )
    application.add_handler(
        CallbackQueryHandler(smart_vpn_add_domain_prompt_callback, pattern="^smart:add_domain$")
    )

    # Free-text handlers (device naming, custom domain, support message): each checks its
    # own user_data flag and no-ops if unset. PTB only runs the first *matching* handler
    # within a group, so each is registered in its own group — otherwise only
    # device_name_message_handler would ever see a text message, even when a different
    # flag (e.g. "awaiting support message") was the one actually set.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, device_name_message_handler), group=1
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, custom_domain_message_handler), group=2
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, support_message_handler), group=3
    )

    application.add_error_handler(on_error)
    return application


async def run() -> None:
    """Runs Telegram polling and the internal notify HTTP server in the same event loop —
    the bot is one process with two inbound surfaces: Telegram updates, and backend-pushed
    notifications (see app/notify_server.py)."""
    settings = get_settings()
    application = build_application()

    notify_app = create_notify_app(application, settings)
    uvicorn_config = uvicorn.Config(
        notify_app, host=settings.notify_host, port=settings.notify_port, log_level="warning"
    )
    server = uvicorn.Server(uvicorn_config)

    assert application.updater is not None  # always set by Application.builder().build()
    updater = application.updater

    async with application:
        await application.start()
        await updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("bot_starting", notify_port=settings.notify_port)
        try:
            await server.serve()
        finally:
            await updater.stop()
            await application.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
