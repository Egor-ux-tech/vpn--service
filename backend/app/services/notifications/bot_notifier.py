"""Delivers a notification by asking the bot's internal `/notify` endpoint to send a
Telegram message. Failures are logged and swallowed here — a notification delivery problem
must never fail the business operation that triggered it (e.g. a subscription still expires
correctly even if the "your subscription expired" message can't be delivered right now).
"""

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


class BotNotifier:
    def __init__(
        self, bot_notify_base_url: str, internal_service_token: str, timeout_seconds: float = 10.0
    ) -> None:
        self._base_url = bot_notify_base_url.rstrip("/")
        self._token = internal_service_token
        self._timeout = timeout_seconds

    async def notify(self, *, telegram_id: int, message: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/notify",
                    json={"telegram_id": telegram_id, "message": message},
                    headers={"X-Internal-Token": self._token},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("notification_delivery_failed", telegram_id=telegram_id, error=str(exc))
