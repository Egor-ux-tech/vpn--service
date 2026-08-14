"""The public subscription-delivery endpoint — GET /sub/{token}.

Mounted directly on the app (see app/main.py), not under /api/v1: this is not part of the
authenticated JSON API surface (no X-Internal-Token, no bearer JWT — the token in the path
*is* the credential, matching every subscription-panel convention (Marzban, 3x-ui, Xray,
...) a VPN client like Happ already expects a short, top-level, copy-pasteable URL for.

Rate limited far more strictly than the API default (see
settings.subscription_link_rate_limit) and every failure mode returns the exact same
generic 404 — see SubscriptionDeliveryService for why.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import get_settings
from app.core.deps import get_subscription_delivery_service
from app.core.rate_limit import limiter
from app.services.subscription_delivery.delivery_service import SubscriptionDeliveryService

router = APIRouter(tags=["subscription-delivery"])

_settings = get_settings()


@router.get("/sub/{token}")
@limiter.limit(_settings.subscription_link_rate_limit)
async def get_subscription(
    request: Request,  # noqa: ARG001 -- required by slowapi to key-rate-limit per client IP
    token: str,
    delivery: Annotated[SubscriptionDeliveryService, Depends(get_subscription_delivery_service)],
) -> Response:
    format_hint = request.query_params.get("format")
    content, content_type = await delivery.deliver(token, format_hint=format_hint)
    return Response(content=content, media_type=content_type)
