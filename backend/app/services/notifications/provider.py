"""Notification transport abstraction. The backend decides *when* a user should be
notified (subscription expired, payment succeeded, ...); *how* the message reaches them is
swappable — MVP ships `BotNotifier`, which asks the Telegram bot to deliver it, since the
bot already owns the Telegram Bot API connection. A future email/push provider is a new
adapter behind the same interface.
"""

from typing import Protocol


class NotificationProvider(Protocol):
    async def notify(self, *, telegram_id: int, message: str) -> None: ...
