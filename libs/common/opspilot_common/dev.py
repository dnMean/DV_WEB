"""Dev-only helpers."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query

from .auth import get_auth_settings, require_internal
from .demo_data import extra_count
from .errors import AppError


def reset_router(reset: Callable[[int], None]) -> APIRouter:
    """POST /internal/reset[?extra_orders=N]: restore seed data (+N generated demo orders, default
    DEMO_EXTRA_ORDERS). Needs ALLOW_RESET=true and X-Internal-Secret."""
    router = APIRouter()

    @router.post("/internal/reset", include_in_schema=False, dependencies=[Depends(require_internal)])
    def _reset(extra_orders: int | None = Query(None, ge=0, le=1000)):
        if not get_auth_settings().ALLOW_RESET:
            raise AppError(403, "reset_disabled", "ALLOW_RESET chưa bật")
        extra = extra_count() if extra_orders is None else extra_orders
        reset(extra)
        return {"status": "reset", "extra_orders": extra}

    return router
