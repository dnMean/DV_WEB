import os

# Tests never touch the real Postgres: force an in-memory SQLite DB before app import.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["INTERNAL_SECRET"] = "test-internal"
os.environ["ALLOW_RESET"] = "true"
os.environ["OUTBOX_INTERVAL_SECONDS"] = "0"
os.environ["PRODUCT_URL"] = "http://product"
os.environ["PAYMENT_URL"] = "http://payment"
os.environ["SHIPPING_URL"] = "http://shipping"
os.environ["DEMO_EXTRA_ORDERS"] = "0"  # unit tests use the 5 hand-written orders
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SYSTEM_TOKEN_SECRET", "test-system-secret")

import json  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from opspilot_common.auth import create_access_token  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class Downstream:
    """Fake Product/Payment/Shipping. Records POST calls; `fail` makes the next N calls return 503."""

    def __init__(self):
        self.calls: list[dict] = []
        self.fail = 0
        # product id -> [name, price, stock]
        self.products = {3: ["Sạc nhanh Anker 20W USB-C", 350_000, 45], 4: ["Cáp sạc USB-C Baseus 1m", 150_000, 80],
                         8: ["Sạc dự phòng Xiaomi 10000mAh", 400_000, 0]}
        self.payments: dict[int, dict] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            self.fail -= 1
            return httpx.Response(503, json={"error": "down", "message": ""})
        path = request.url.path
        if request.method == "GET" and path == "/internal/products":
            ids = [int(i) for i in request.url.params["ids"].split(",")]
            return httpx.Response(200, json=[{"id": i, "name": p[0], "price": p[1], "stock": p[2]}
                                             for i, p in self.products.items() if i in ids])
        body = json.loads(request.content)
        self.calls.append({"url": str(request.url), "body": body, "key": request.headers.get("Idempotency-Key"),
                           "secret": request.headers.get("X-Internal-Secret")})
        if path == "/internal/inventory/reserve":
            short = [i for i in body["items"] if self.products[i["product_id"]][2] < i["qty"]]
            if short:
                return httpx.Response(409, json={"error": "out_of_stock", "message": "Không đủ hàng"})
            for i in body["items"]:
                self.products[i["product_id"]][2] -= i["qty"]
            return httpx.Response(200, json={"replayed": False, "items": []})
        if path == "/internal/payments":
            payment = self.payments.setdefault(body["order_id"], {**body, "status": "SUCCESS"})
            return httpx.Response(200, json=payment)
        return httpx.Response(200, json={"replayed": False})


@pytest.fixture
def downstream():
    return Downstream()


@pytest.fixture
def client(downstream):
    Base.metadata.drop_all(engine)  # fresh seeded DB per test
    app.state.transport = httpx.MockTransport(downstream.handler)
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
