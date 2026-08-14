import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_REDACT_KEYS = {
    "private_key",
    "privatekey",
    "password",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "payment_provider_key",
    "webhook_secret",
    # A rendered WireGuard config is exactly as sensitive as the private key it contains
    # (see wireguard_formatter.py) — the bot and vpn-agent's own _REDACT_KEYS already
    # include this; added here for consistency now that the backend also handles
    # subscription-link tokens and rendered config content directly.
    "config_text",
    "subscription_token",
    "subscription_url",
    # A VLESS UUID is a bearer credential (anyone holding it can connect as that user —
    # see docs/vless.md), exactly as sensitive as a WireGuard private key.
    "vless_uuid",
    "uuid",
    # Defensive: the Reality private key never reaches this codebase (it lives only on
    # the VLESS node's filesystem — see docs/xray-agent.md) and xray_agent_shared_secret
    # is already caught by the generic "secret" entry above, but both are listed
    # explicitly for the same belt-and-suspenders reason config_text is.
    "reality_private_key",
    "xray_agent_shared_secret",
}


def _redact_sensitive(_logger: Any, _method_name: str, event_dict: Any) -> Any:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def safe_request_path(path: str) -> str:
    """Masks known secret-bearing path segments before they reach a log line. Currently
    just GET /sub/{token} (see app/api/sub.py) — the subscription-delivery token is a
    bearer credential embedded directly in the URL path, so `request.url.path` is not safe
    to log verbatim the way it is for every other route. A single shared function (not
    inline checks scattered across middleware.py and errors.py, the two places that log a
    request path) so every call site agrees on the same rule."""
    if path.startswith("/sub/"):
        return "/sub/***"
    return path


def _add_request_id(_logger: Any, _method_name: str, event_dict: Any) -> Any:
    # setdefault, not a plain assignment: a caller that already knows the real request_id
    # (see app/core/errors.py's handle_unexpected_error, which reads it from request.state
    # because the contextvar isn't reliably set by the time that handler runs) must not
    # have it silently overwritten back to the request_id_ctx default here.
    event_dict.setdefault("request_id", request_id_ctx.get())
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
