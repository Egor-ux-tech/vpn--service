import logging
import sys
from typing import Any

import structlog

# A VLESS UUID is a bearer credential (anyone holding it can connect as that user — see
# docs/vless.md), exactly as sensitive as a WireGuard private key; reality_private_key
# and xray_agent_shared_secret are listed defensively even though no code path in this
# service ever reads or handles them (the Reality private key lives only on this node's
# filesystem, read directly by Xray-core itself — see infrastructure/ansible/roles/xray
# — and the shared secret only ever appears as a config value, never in an event dict).
_REDACT_KEYS = {
    "private_key",
    "privatekey",
    "reality_private_key",
    "secret",
    "xray_agent_shared_secret",
    "authorization",
    "signature",
    "uuid",
    "vless_uuid",
}


def _redact_sensitive(_logger: Any, _method_name: str, event_dict: Any) -> Any:
    for key in list(event_dict.keys()):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "***REDACTED***"
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
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
