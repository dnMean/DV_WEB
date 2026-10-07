import os
import tempfile

os.environ.update({
    "SERVICE_URLS": "http://order,http://product,http://payment,http://approval",
    "APPROVAL_URL": "http://approval",
    "INTERNAL_SECRET": "test-internal",
    "AUDIT_LOG_PATH": os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
    "REGISTRY_REFRESH_SECONDS": "3600",
    "ALLOW_RESET": "true",
})
os.environ["DEMO_EXTRA_ORDERS"] = "0"  # unit tests use the 5 hand-written orders
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SYSTEM_TOKEN_SECRET", "test-system-secret")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI, Header, Path, Query, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from opspilot_common.auth import create_access_token  # noqa: E402
from opspilot_common.tools import agent_tool  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls: list[dict] = []
        self.fail_next: list[int] = []
        self.tickets: dict[str, dict] = {}


def _fake_services(rec: Recorder) -> dict[str, FastAPI]:
    order = FastAPI()

    @order.get("/orders/{order_id}", summary="Lấy đơn", description="Dùng khi hỏi đơn.",
               openapi_extra=agent_tool("get_order", "low", ["customer", "staff"]))
    def get_order(request: Request, order_id: int = Path(..., ge=1, description="Mã đơn")):
        rec.calls.append({"tool": "get_order", "order_id": order_id, "headers": dict(request.headers)})
        if rec.fail_next:
            return JSONResponse(status_code=rec.fail_next.pop(0), content={"error": "boom", "message": "x"})
        if order_id == 1004:
            return JSONResponse(status_code=403, content={"error": "forbidden", "message": "không có quyền"})
        return {"id": order_id, "note": "x" * (10000 if order_id == 9 else 1)}

    @order.post("/orders/{order_id}/cancel", summary="Huỷ đơn",
                openapi_extra=agent_tool("cancel_order", "medium", ["customer", "staff"]))
    def cancel(request: Request, order_id: int):
        rec.calls.append({"tool": "cancel_order", "headers": dict(request.headers)})
        if rec.fail_next:
            return JSONResponse(status_code=rec.fail_next.pop(0), content={"error": "boom", "message": "x"})
        return {"id": order_id, "status": "CANCELLED"}

    @order.get("/internal/secret")  # no x-agent-tool: must not be exposed
    def hidden():
        return {}

    product = FastAPI()

    @product.get("/inventory/{product_id}", summary="Tồn kho",
                 openapi_extra=agent_tool("check_stock", "low", ["customer", "staff"]))
    def stock(product_id: int, verbose: bool | None = Query(None)):
        return {"product_id": product_id, "stock": 3}

    payment = FastAPI()

    class RefundIn(BaseModel):
        order_id: int = Field(..., ge=1)
        amount: int = Field(..., gt=0)
        reason: str

    @payment.post("/refunds", summary="Hoàn tiền",
                  openapi_extra=agent_tool("refund_payment", "high", ["customer", "staff"],
                                           dedup_fields=["order_id"], precheck="/refunds/validate"))
    def refund(body: RefundIn, request: Request, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
        rec.calls.append({"tool": "refund_payment", "body": body.model_dump(), "headers": dict(request.headers)})
        return {"refund": {"id": 1, "amount": body.amount}, "replayed": False}

    @payment.post("/refunds/validate")
    def validate(body: RefundIn, request: Request):
        rec.calls.append({"tool": "precheck", "body": body.model_dump(), "headers": dict(request.headers)})
        if body.order_id == 1002:
            return JSONResponse(status_code=409, content={"error": "order_in_transit", "message": "đang giao"})
        return {"eligible": True}

    approval = FastAPI()

    @approval.post("/tickets")
    async def create_ticket(request: Request):
        body = await request.json()
        rec.calls.append({"tool": "approval.create", "body": body, "headers": dict(request.headers)})
        for t in rec.tickets.values():
            if (t["tool"] == body["tool"] and t["dedup_arguments"] == body["dedup_arguments"]
                    and t["status"] != "REJECTED"):
                return t
        ticket = {"id": f"t{len(rec.tickets) + 1}", "status": "PENDING", "result": None, **body}
        rec.tickets[ticket["id"]] = ticket
        return JSONResponse(status_code=201, content=ticket)

    @approval.post("/tickets/{ticket_id}/approve", summary="Duyệt",
                   openapi_extra=agent_tool("approve_ticket", "medium", ["staff"], confirm_args=["ticket_id"]))
    def approve(ticket_id: str):
        rec.calls.append({"tool": "approve_ticket", "ticket_id": ticket_id})
        return {"id": ticket_id, "status": "EXECUTED"}

    @approval.get("/tickets/{ticket_id}")
    def get_ticket(ticket_id: str, request: Request):
        assert request.headers["x-internal-secret"] == "test-internal"
        if ticket_id not in rec.tickets:
            return JSONResponse(status_code=404, content={"error": "not_found", "message": ""})
        return rec.tickets[ticket_id]

    return {"order": order, "product": product, "payment": payment, "approval": approval}


class HostRouter(httpx.AsyncBaseTransport):
    def __init__(self, apps: dict[str, FastAPI]):
        self.transports = {host: httpx.ASGITransport(app=a) for host, a in apps.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.transports[request.url.host].handle_async_request(request)


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def client(rec):
    from app.main import app

    app.state.transport = HostRouter(_fake_services(rec))
    with TestClient(app) as c:
        yield c


def _headers(user_id: int, username: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, username, role)}"}


@pytest.fixture
def alice():
    return _headers(1, "alice", "customer")


@pytest.fixture
def staff():
    return _headers(3, "staff1", "staff")
