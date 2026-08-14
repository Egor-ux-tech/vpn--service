"""Verifies that a request genuinely came from the backend's WireGuardProvider.

Every request must carry an HMAC-SHA256 signature (`X-Signature`) over the raw request body,
computed with the shared secret configured for this server, plus an `X-Timestamp` header
checked against a freshness window — this bounds how long a captured request could be
replayed even if the signature itself were somehow intercepted.
"""

import time

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import AgentSettings, get_settings


def _constant_time_compare(a: str, b: str) -> bool:
    import hmac as _hmac

    return _hmac.compare_digest(a.encode(), b.encode())


def _sign(payload: bytes, secret: str) -> str:
    import hashlib
    import hmac as _hmac

    return _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


async def verify_signed_request(
    request: Request,
    settings: AgentSettings = Depends(get_settings),
    x_signature: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
) -> None:
    if not x_signature or not x_timestamp:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing signature headers")

    try:
        timestamp = int(x_timestamp)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid timestamp") from exc

    if abs(time.time() - timestamp) > settings.signature_max_skew_seconds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Stale request")

    body = await request.body()
    expected = _sign(body, settings.vpn_agent_shared_secret)
    if not _constant_time_compare(expected, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
