from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from opspilot_common.dev import reset_router
from opspilot_common.errors import install_error_handlers
from opspilot_common.logging import RequestIDMiddleware, setup_logging

from app.config import get_settings
from app.db import Base, SessionLocal, engine, init_db
from app.outbox import outbox
from app.routers import checkout, internal, orders
from app.seed import seed

settings = get_settings()
logger = setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed(db)
    # Tests inject app.state.transport (httpx.MockTransport) before startup.
    app.state.http = httpx.Client(transport=getattr(app.state, "transport", None))
    outbox.start(app.state.http, settings.OUTBOX_INTERVAL_SECONDS)
    outbox.flush()
    logger.info("order service ready")
    yield
    outbox.stop()
    app.state.http.close()


app = FastAPI(title="OpsPilot Order Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)
app.include_router(orders.router)
app.include_router(checkout.router)
app.include_router(internal.router)


def _reset(extra: int) -> None:
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as db:
        seed(db, extra)


app.include_router(reset_router(_reset))


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
