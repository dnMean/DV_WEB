import os

# Tests never touch the real Postgres: force an in-memory SQLite DB before app import.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["INTERNAL_SECRET"] = "test-internal"
os.environ["ALLOW_RESET"] = "true"
os.environ["OUTBOX_INTERVAL_SECONDS"] = "0"
os.environ["ORDER_URL"] = "http://order"
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
    def __init__(self):
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append({"url": str(request.url), "body": json.loads(request.content),
                           "key": request.headers.get("Idempotency-Key")})
        return httpx.Response(200, json={})


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
