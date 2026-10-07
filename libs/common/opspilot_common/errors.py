"""Uniform error format: {"error": "<code>", "message": "<text>"}."""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("opspilot.errors")

_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "invalid_arguments",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "service_unavailable",
    504: "timeout",
}


class AppError(Exception):
    """Raise anywhere in a service to return a structured error response."""

    def __init__(self, status_code: int, error: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message
        self.extra = extra or {}


def error_body(error: str, message: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": error, "message": message, **(extra or {})}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.error, exc.message, exc.extra))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            body = error_body(detail["error"], str(detail.get("message", "")))
        else:
            body = error_body(_DEFAULT_CODES.get(exc.status_code, "error"), str(detail))
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors()[:3]:
            loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
            parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return JSONResponse(status_code=422, content=error_body("validation_error", "; ".join(parts) or "Dữ liệu không hợp lệ"))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content=error_body("internal_error", "Lỗi hệ thống"))
