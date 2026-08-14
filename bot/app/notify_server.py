"""Small internal HTTP surface the backend calls to push a Telegram message to a user (e.g.
"your subscription expired") — it does not implement any business logic itself, only
delivery. Runs alongside polling in the same process/event loop (see app/main.py).
"""

from fastapi import FastAPI, Header, HTTPException, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from starlette.responses import Response
from telegram.error import TelegramError
from telegram.ext import Application as PTBApplication

from app.core.config import BotSettings
from app.core.logging import get_logger
from app.core.metrics import NOTIFY_REQUESTS_TOTAL
from app.core.security import constant_time_compare

logger = get_logger(__name__)


class NotifyRequest(BaseModel):
    telegram_id: int
    message: str


def create_notify_app(ptb_application: PTBApplication, settings: BotSettings) -> FastAPI:
    app = FastAPI(title="Bot Notify", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/notify", status_code=204)
    async def notify(
        payload: NotifyRequest, x_internal_token: str | None = Header(default=None)
    ) -> None:
        if not x_internal_token or not constant_time_compare(
            x_internal_token, settings.internal_service_token
        ):
            NOTIFY_REQUESTS_TOTAL.labels(outcome="unauthorized").inc()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal token")

        try:
            await ptb_application.bot.send_message(
                chat_id=payload.telegram_id, text=payload.message
            )
            NOTIFY_REQUESTS_TOTAL.labels(outcome="sent").inc()
        except TelegramError as exc:
            NOTIFY_REQUESTS_TOTAL.labels(outcome="failed").inc()
            # A user who blocked the bot, or an invalid chat, must not fail the caller's
            # business operation (e.g. subscription expiry) — log and swallow.
            logger.warning(
                "notify_delivery_failed", telegram_id=payload.telegram_id, error=str(exc)
            )
        return None

    return app
