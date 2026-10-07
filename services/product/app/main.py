from contextlib import asynccontextmanager

from fastapi import FastAPI

from opspilot_common.dev import reset_router
from opspilot_common.errors import install_error_handlers
from opspilot_common.logging import RequestIDMiddleware, setup_logging

from app.config import get_settings
from app.db import Base, SessionLocal, engine, init_db
from app.routers import internal, products
from app.seed import seed

settings = get_settings()
logger = setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed(db)
    logger.info("product service ready")
    yield


app = FastAPI(title="OpsPilot Product Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)
app.include_router(products.router)
app.include_router(internal.router)


def _reset(_extra: int) -> None:
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as db:
        seed(db)


app.include_router(reset_router(_reset))


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
