import json
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ.update({
    "INTERNAL_SECRET": "test-internal",
    "GATEWAY_URL": "http://gateway",
    "AUTH_URL": "http://auth",
    "GUARD_INPUT_RULES": "true",
    "GUARD_INPUT_LLM": "false",
    "GUARD_TOOL_OUTPUT": "true",
    "GUARD_OUTPUT_PII": "true",
    "AGENT_MAX_STEPS": "6",
    "AGENT_MAX_TOKENS": "12000",
    "AGENT_MAX_SAME_CALL": "2",
})
os.environ["ALLOW_RESET"] = "true"
os.environ["DEMO_EXTRA_ORDERS"] = "0"  # unit tests use the 5 hand-written orders
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SYSTEM_TOKEN_SECRET", "test-system-secret")

from collections.abc import Callable  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from opspilot_common.auth import create_access_token  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.llm import LLMResponse, ToolCall  # noqa: E402
from app.main import app  # noqa: E402

TOOLS = [
    {"type": "function", "function": {"name": n, "description": n, "parameters": {"type": "object", "properties": {}}}}
    for n in ("get_order", "get_shipment", "get_payment", "refund_payment", "list_my_orders")
]


def call(name: str, args: dict, id_: str | None = None) -> ToolCall:
    return ToolCall(id=id_ or f"call_{name}", name=name, arguments=json.dumps(args))


def reply(text: str, tokens: int = 100) -> LLMResponse:
    return LLMResponse(content=text, prompt_tokens=tokens, completion_tokens=10)


def tools(*calls: ToolCall, tokens: int = 100) -> LLMResponse:
    return LLMResponse(content="", tool_calls=list(calls), prompt_tokens=tokens, completion_tokens=10)


class FakeLLM:
    """Returns scripted responses in order; records the messages it was sent."""

    def __init__(self):
        self.script: list[LLMResponse | Exception | Callable[[list], LLMResponse]] = []
        self.received: list[list[dict[str, Any]]] = []

    def chat(self, messages, tools=None):
        self.received.append([dict(m) for m in messages])
        if not self.script:
            return reply("(hết kịch bản)")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(messages) if callable(item) else item


class FakeGateway:
    def __init__(self):
        self.results: dict[str, dict] = {}
        self.invocations: list[dict] = []
        self.me = {"id": 1, "username": "alice", "email": "alice@example.com", "phone": "0901234567"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/tools":
            return httpx.Response(200, json=TOOLS)
        if request.url.path == "/auth/me":
            return httpx.Response(200, json=self.me)
        if request.url.path == "/invoke":
            body = json.loads(request.content)
            self.invocations.append(body)
            result = self.results.get(body["tool"], {"status": "ok", "data": {"ok": True}})
            return httpx.Response(200, json=result)
        return httpx.Response(404, json={"error": "not_found", "message": ""})


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def client(llm, gateway):
    Base.metadata.drop_all(engine)
    app.state.llm = llm
    app.state.transport = httpx.MockTransport(gateway.handler)
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
