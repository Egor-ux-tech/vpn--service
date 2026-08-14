from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_ctx

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for domain/service errors that map to a clean HTTP response."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "app_error"

    def __init__(self, message: str, *, error_code: str | None = None, details: Any = None) -> None:
        self.message = message
        self.details = details
        if error_code:
            self.error_code = error_code
        super().__init__(message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "validation_error"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "permission_denied"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"


class LimitExceededError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "limit_exceeded"


class ExternalServiceError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "external_service_error"


def _request_id_for(request: Request) -> str:
    """Prefers request.state.request_id (set by RequestContextMiddleware) over the
    request_id_ctx contextvar: for the bare-Exception/500 path specifically, that
    contextvar has already been reset by the time this runs (ServerErrorMiddleware, which
    dispatches the 500 handler, wraps *outside* every add_middleware() layer — see the
    comment in RequestContextMiddleware.dispatch), while request.state — a plain attribute
    on this same Request object — is unaffected by that boundary. Other handlers
    (AppError, validation, HTTPException) run inside RequestContextMiddleware and would get
    the same value either way; this is written once so all of them go through one path."""
    return getattr(request.state, "request_id", None) or request_id_ctx.get()


def _error_body(
    request: Request, error_code: str, message: str, details: Any = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": error_code,
            "message": message,
            "details": details,
            "request_id": _request_id_for(request),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error",
            path=request.url.path,
            error_code=exc.error_code,
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, exc.error_code, exc.message, exc.details),
            headers={"X-Error-Code": exc.error_code},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_body(request, "validation_error", "Invalid request", exc.errors()),
            headers={"X-Error-Code": "validation_error"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, "http_error", str(exc.detail)),
            headers={"X-Error-Code": "http_error"},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            request_id=_request_id_for(request),
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(request, "internal_error", "Internal server error"),
            headers={"X-Error-Code": "internal_error"},
        )
