"""End-to-end fixtures: talk to the running docker-compose stack over HTTP."""
import os
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

URL = {
    "auth": os.getenv("AUTH_URL", "http://auth:8000"),
    "order": os.getenv("ORDER_URL", "http://order:8000"),
    "product": os.getenv("PRODUCT_URL", "http://product:8000"),
    "payment": os.getenv("PAYMENT_URL", "http://payment:8000"),
    "shipping": os.getenv("SHIPPING_URL", "http://shipping:8000"),
    "gateway": os.getenv("GATEWAY_URL", "http://gateway:8000"),
    "approval": os.getenv("APPROVAL_URL", "http://approval:8000"),
    "agent": os.getenv("AGENT_URL", "http://agent:8000"),
}
INTERNAL = {"X-Internal-Secret": os.environ["INTERNAL_SECRET"]}
RESETTABLE = ["product", "order", "payment", "shipping", "approval", "gateway"]


class Api:
    def __init__(self):
        self.http = httpx.Client(timeout=30.0)
        self._tokens: dict[str, str] = {}

    def token(self, username: str) -> dict[str, str]:
        if username not in self._tokens:
            r = self.http.post(f"{URL['auth']}/auth/login", json={"username": username, "password": "password123"})
            r.raise_for_status()
            self._tokens[username] = r.json()["access_token"]
        return {"Authorization": f"Bearer {self._tokens[username]}"}

    # --- raw service calls ----------------------------------------------------------------
    def get(self, service: str, path: str, user: str = "staff1", **kw) -> httpx.Response:
        return self.http.get(f"{URL[service]}{path}", headers=self.token(user), **kw)

    def post(self, service: str, path: str, user: str = "staff1", json: Any = None, headers=None) -> httpx.Response:
        return self.http.post(f"{URL[service]}{path}", headers={**self.token(user), **(headers or {})}, json=json)

    # --- domain helpers ---------------------------------------------------------------------
    def invoke(self, user: str, tool: str, arguments: dict, conversation_id: str = "e2e") -> dict:
        r = self.post("gateway", "/invoke", user, {"tool": tool, "arguments": arguments,
                                                    "conversation_id": conversation_id})
        body = r.json()
        body["_http"] = r.status_code
        return body

    def approve(self, ticket_id: str, note: str = "") -> dict:
        return self.post("approval", f"/tickets/{ticket_id}/approve", "staff1", {"note": note}).json()

    def reject(self, ticket_id: str, note: str = "") -> dict:
        return self.post("approval", f"/tickets/{ticket_id}/reject", "staff1", {"note": note}).json()

    def tickets(self) -> list[dict]:
        return self.get("approval", "/tickets", params={"limit": 200}).json()

    def order(self, order_id: int) -> dict:
        return self.get("order", f"/orders/{order_id}").json()

    def payment(self, order_id: int) -> dict:
        return self.get("payment", "/payments", params={"order_id": order_id}).json()

    def shipment(self, order_id: int) -> httpx.Response:
        return self.get("shipping", f"/shipments/{order_id}")

    def stock(self, product_id: int) -> int:
        return self.http.get(f"{URL['product']}/inventory/{product_id}").json()["stock"]

    def advance(self, order_id: int, status: str) -> httpx.Response:
        return self.post("shipping", f"/shipments/{order_id}/advance", "staff1",
                         {"status": status, "location": "Kho", "description": f"-> {status}"})


def eventually(check: Callable[[], Any], timeout: float = 8.0, interval: float = 0.2) -> Any:
    """Retry `check` until it stops raising AssertionError (outbox delivery is asynchronous)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return check()
        except AssertionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(interval)


@pytest.fixture(scope="session")
def api() -> Api:
    return Api()


@pytest.fixture(autouse=True)
def reset(api: Api):
    for name in RESETTABLE:
        r = api.http.post(f"{URL[name]}/internal/reset", params={"extra_orders": 0}, headers=INTERNAL)
        assert r.status_code == 200, f"reset {name}: {r.status_code} {r.text}"
