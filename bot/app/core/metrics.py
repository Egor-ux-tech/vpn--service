from prometheus_client import Counter

BOT_ERRORS_TOTAL = Counter(
    "bot_errors_total", "Unhandled errors raised while processing a Telegram update"
)
NOTIFY_REQUESTS_TOTAL = Counter(
    "bot_notify_requests_total",
    "Notification delivery attempts via the internal /notify endpoint",
    ["outcome"],
)
