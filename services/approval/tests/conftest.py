import json
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["INTERNAL_SECRET"] = "test-internal"
os.environ["GATEWAY_URL"] = "http://gateway"
os.environ["AGENT_URL"] = "http://agent"
os.environ["ALLOW_RESET"] = "true"
os.environ["DEMO_EXTRA_ORDERS"] = "0"  # unit tests use the 5 hand-written orders
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SYSTEM_TOKEN_SECRET", "test-system-secret")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from opspilot_common.auth import create_access_token  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class FakeDownstream:
    """Records calls to Gateway/Agent; `execute_result` is what the gateway returns."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.execute_result: dict = {"status": "ok", "data": {"refund": {"id": 1}}}
        self.gateway_down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        self.calls.append((str(request.url), body))
        assert request.headers["X-Internal-Secret"] == "test-internal"
        if request.url.host == "gateway":
            if self.gateway_down:
                raise httpx.ConnectError("down")
            return httpx.Response(200, json=self.execute_result)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def downstream():
    return FakeDownstream()


@pytest.fixture
def client(downstream):
    Base.metadata.drop_all(engine)
    app.state.transport = httpx.MockTransport(downstream.handler)
    with TestClient(app) as c:
        yield c


INTERNAL = {"X-Internal-Secret": "test-internal"}


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
