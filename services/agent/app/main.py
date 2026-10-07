from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from opspilot_common.errors import install_error_handlers
from opspilot_common.logging import RequestIDMiddleware, setup_logging

from app.config import get_settings
from app.db import init_db
from app.llm import OpenAIClient
from app.routers import chat

settings = get_settings()
logger = setup_logging(settings.SERVICE_NAME, settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Tests inject app.state.transport / app.state.llm before startup.
    app.state.http = httpx.Client(transport=getattr(app.state, "transport", None))
    if getattr(app.state, "llm", None) is None:
        app.state.llm = OpenAIClient(settings)
    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY == "sk-xxx":
        logger.warning("OPENAI_API_KEY is not set: /chat will answer with status=error")
    logger.info("agent service ready (model=%s)", settings.OPENAI_MODEL)
    yield
    app.state.http.close()


app = FastAPI(title="OpsPilot Agent Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
install_error_handlers(app)
app.include_router(chat.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
