import os

# Tests never touch the real Postgres: force an in-memory SQLite DB before app import.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["INTERNAL_SECRET"] = "test-internal"
os.environ["ALLOW_RESET"] = "true"
os.environ["OUTBOX_INTERVAL_SECONDS"] = "0"
os.environ["ORDER_URL"] = "http://order"
os.environ["SHIPPING_URL"] = "http://shipping"
os.environ["DEMO_EXTRA_ORDERS"] = "0"  # unit tests use the 5 hand-written orders
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SYSTEM_TOKEN_SECRET", "test-system-secret")

import json  # noqa: E402
import re  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from opspilot_common.auth import create_access_token  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class World:
    """In-memory Order + Shipping answering Payment's internal calls (seed from docs/USECASES.md)."""

    def __init__(self):
        self.orders = {1001: [1, "DELIVERED"], 1002: [1, "SHIPPING"], 1003: [1, "PAID"],
                       1004: [2, "PENDING"], 1005: [2, "PAID"]}
        self.shipments = {1001: "DELIVERED", 1002: "IN_TRANSIT", 1003: "WAITING_PICKUP", 1005: "WAITING_PICKUP"}
        self.refund_applied: list[tuple[int, dict]] = []
        self.shipping_down = False
        self.order_sync_down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Internal-Secret"] == "test-internal"
        path = request.url.path
        if m := re.fullmatch(r"/internal/orders/(\d+)", path):
            oid = int(m[1])
            if oid not in self.orders:
                return httpx.Response(404, json={"error": "order_not_found", "message": ""})
            return httpx.Response(200, json={"id": oid, "user_id": self.orders[oid][0], "status": self.orders[oid][1]})
        if m := re.fullmatch(r"/internal/orders/(\d+)/refund-applied", path):
            if self.order_sync_down:
                return httpx.Response(503, json={"error": "down", "message": ""})
            self.refund_applied.append((int(m[1]), json.loads(request.content)))
            return httpx.Response(200, json={})
        if self.shipping_down:
            raise httpx.ConnectError("shipping down")
        if m := re.fullmatch(r"/internal/shipments/(\d+)", path):
            oid = int(m[1])
            if oid not in self.shipments:
                return httpx.Response(404, json={"error": "shipment_not_found", "message": ""})
            return httpx.Response(200, json={"order_id": oid, "status": self.shipments[oid]})
        if m := re.fullmatch(r"/internal/shipments/(\d+)/cancel", path):
            oid = int(m[1])
            if self.shipments[oid] not in ("WAITING_PICKUP", "CANCELLED"):
                return httpx.Response(409, json={"error": "shipment_already_dispatched", "message": ""})
            self.shipments[oid] = "CANCELLED"
            return httpx.Response(200, json={"order_id": oid, "status": "CANCELLED"})
        return httpx.Response(404, json={"error": "not_found", "message": path})


@pytest.fixture
def world():
    return World()


@pytest.fixture
def client(world):
    Base.metadata.drop_all(engine)  # fresh seeded DB per test
    app.state.transport = httpx.MockTransport(world.handler)
    with TestClient(app) as c:
        yield c


def _headers(user_id: int, username: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, username, role)}"}


@pytest.fixture
def alice():
    return _headers(1, "alice", "customer")


@pytest.fixture
def bob():
    return _headers(2, "bob", "customer")


@pytest.fixture
def staff():
    return _headers(3, "staff1", "staff")
