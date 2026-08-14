import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger, request_id_ctx, safe_request_path
from app.core.metrics import API_ERRORS_TOTAL, HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL

logger = get_logger("http")


def _route_path_template(request: Request) -> str:
    """Groups metrics by route template (e.g. /devices/{device_id}), not the literal
    path, so per-ID paths don't create unbounded label cardinality in Prometheus."""
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        path = _route_path_template(request)
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method, path=path, status_code=str(response.status_code)
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, path=path).observe(duration)
        if response.status_code >= 400:
            error_code = response.headers.get("x-error-code", "unknown_error")
            API_ERRORS_TOTAL.labels(error_code=error_code).inc()
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID for correlation and logs each request without sensitive data."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming_id = request.headers.get("x-request-id")
        req_id = incoming_id or uuid.uuid4().hex
        # Also stashed on request.state, not just the contextvar: this middleware runs
        # *inside* Starlette's ServerErrorMiddleware (FastAPI always wraps the app in it
        # for the bare-Exception/500 handler, outside every add_middleware() layer — see
        # Starlette's Starlette.build_middleware_stack). When an exception unwinds through
        # this dispatch()'s `finally` below, request_id_ctx gets reset *before*
        # ServerErrorMiddleware's handler (handle_unexpected_error) runs, so that handler
        # would see the sentinel "-", not the real ID. request.state isn't contextvar-based
        # — it's a plain attribute on the same Request object the 500 handler receives — so
        # it survives that boundary. See app/core/errors.py's _request_id_for.
        request.state.request_id = req_id
        token = request_id_ctx.set(req_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = req_id
        logger.info(
            "request_completed",
            method=request.method,
            path=safe_request_path(request.url.path),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
