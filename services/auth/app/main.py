from contextlib import asynccontextmanager

from fastapi import FastAPI

from opspilot_common.errors import install_error_handlers
from opspilot_common.logging import RequestIDMiddleware, setup_logging

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.routers import auth
from app.seed import seed

settings = get_settings()
logger = setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed(db)
    logger.info("auth service ready")
    yield


app = FastAPI(title="OpsPilot Auth Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)
app.include_router(auth.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
