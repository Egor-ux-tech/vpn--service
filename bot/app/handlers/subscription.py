from telegram import Update
from telegram.ext import ContextTypes

from app.handlers.common import format_date, get_backend, reply
from app.keyboards.menus import back_to_main, plans_keyboard

STATUS_LABELS = {"active": "🟢 Активна", "expired": "🔴 Истекла", "cancelled": "⚪️ Отменена"}


async def subscription_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    backend = get_backend(context)
    subscription = await backend.get_active_subscription(user.id)

    lines = ["<b>💳 Подписка</b>", ""]
    if subscription:
        lines.append(f"План: {subscription['plan']['name']}")
        lines.append(f"Статус: {STATUS_LABELS.get(subscription['status'], subscription['status'])}")
        lines.append(f"Действует до: {format_date(subscription.get('expires_at'))}")
        lines.append("")
        lines.append("Хотите сменить план или продлить?")
    else:
        lines.append("У вас нет активной подписки.")
        lines.append("Выберите план ниже:")

    plans = await backend.list_plans(user.id)
    await reply(update, "\n".join(lines), plans_keyboard(plans))


async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None or query.data is None:
        return
    plan_id = int(query.data.split(":")[-1])
    backend = get_backend(context)

    payment = await backend.create_payment(user.id, plan_id)
    await query.answer()

    if payment.get("checkout_url"):
        text = (
            "💳 Для оплаты перейдите по ссылке:\n"
            f"{payment['checkout_url']}\n\n"
            "Подписка активируется автоматически сразу после подтверждения платежа."
        )
    else:
        text = "Платёж создан. Подписка активируется после подтверждения оплаты."
    await query.edit_message_text(text, reply_markup=back_to_main())
