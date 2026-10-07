"""One-line JSON logs (ts, service, level, request_id, msg) and X-Request-ID propagation."""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_logger = logging.getLogger("opspilot.http")


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "service": self.service,
            "level": record.levelname,
            "request_id": request_id_var.get(),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str = "INFO") -> logging.Logger:
    """Route root + uvicorn loggers through a single JSON stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    return logging.getLogger(service)


def get_request_id() -> str:
    return request_id_var.get()


def forward_headers() -> dict[str, str]:
    """Headers to attach when calling another service."""
    rid = request_id_var.get()
    return {REQUEST_ID_HEADER: rid} if rid != "-" else {}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Reads X-Request-ID (or generates one), exposes it to logs, echoes it back, logs each request."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _logger.exception("%s %s failed", request.method, request.url.path)
            raise
        else:
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            if request.url.path != "/health":
                _logger.info("%s %s %s %sms", request.method, request.url.path, response.status_code, latency_ms)
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            request_id_var.reset(token)
