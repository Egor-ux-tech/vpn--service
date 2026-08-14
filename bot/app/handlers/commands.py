"""Slash-command entry points — thin wrappers around the same callbacks used by the
inline-keyboard menu, so /vpn and tapping "🔐 Мой VPN" always show identical content."""

from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.devices import devices_list_callback
from app.handlers.profile import profile_callback
from app.handlers.servers import servers_callback
from app.handlers.smart_vpn import smart_vpn_menu_callback
from app.handlers.start import main_menu_callback
from app.handlers.subscription import subscription_menu_callback
from app.handlers.support import support_menu_callback


async def vpn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await main_menu_callback(update, context)


async def servers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await servers_callback(update, context)


async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await subscription_menu_callback(update, context)


async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await devices_list_callback(update, context)


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await support_menu_callback(update, context)


async def smart_vpn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await smart_vpn_menu_callback(update, context)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await profile_callback(update, context)
