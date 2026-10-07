import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from opspilot_common.dev import reset_router
from opspilot_common.errors import install_error_handlers
from opspilot_common.logging import RequestIDMiddleware, setup_logging

from app.audit import AuditLog
from app.config import get_settings
from app.ratelimit import TokenBucketLimiter
from app.registry import Registry
from app.routers import tools

settings = get_settings()
logger = setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)


async def _refresh_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(settings.REGISTRY_REFRESH_SECONDS)
        await app.state.registry.refresh(app.state.http, settings.service_urls, strict=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tests inject app.state.transport (httpx.MockTransport) before startup.
    app.state.http = httpx.AsyncClient(transport=getattr(app.state, "transport", None))
    app.state.registry = Registry()
    app.state.limiter = TokenBucketLimiter()
    app.state.audit = AuditLog(settings.AUDIT_LOG_PATH)
    await app.state.registry.refresh(app.state.http, settings.service_urls, strict=True)
    task = asyncio.create_task(_refresh_loop(app))
    logger.info("gateway ready")
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await app.state.http.aclose()


app = FastAPI(title="OpsPilot Tool Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)
app.include_router(tools.router)


def _reset(_extra: int) -> None:
    app.state.limiter = TokenBucketLimiter()


app.include_router(reset_router(_reset))


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
