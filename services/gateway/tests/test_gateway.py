import json
import os

import pytest

from opspilot_common.auth import create_access_token

from app.invoker import idempotency_key
from app.ratelimit import TokenBucketLimiter
from app.registry import RegistryError, build_tools, merge


def _invoke(client, headers, tool, arguments, conversation_id="c1"):
    return client.post("/invoke", headers=headers,
                       json={"tool": tool, "arguments": arguments, "conversation_id": conversation_id})


def test_tools_openai_format_and_filtered(client, alice):
    tools = client.get("/tools", headers=alice).json()
    names = sorted(t["function"]["name"] for t in tools)
    assert names == ["cancel_order", "check_stock", "get_order", "refund_payment"]  # approve_ticket: staff only
    get_order = next(t for t in tools if t["function"]["name"] == "get_order")
    assert get_order["type"] == "function"
    assert set(get_order["function"]) == {"name", "description", "parameters"}  # no internal metadata
    params = get_order["function"]["parameters"]
    assert params["additionalProperties"] is False
    assert params["required"] == ["order_id"]
    assert params["properties"]["order_id"]["type"] == "integer"
    assert params["properties"]["order_id"]["description"] == "Mã đơn"
    assert get_order["function"]["description"] == "Lấy đơn. Dùng khi hỏi đơn."


def test_tools_filtered_by_role(client):
    other = {"Authorization": f"Bearer {create_access_token(9, 'x', 'auditor')}"}
    assert client.get("/tools", headers=other).json() == []


def test_body_params_flattened_and_refs_resolved(client, alice):
    tools = {t["function"]["name"]: t["function"] for t in client.get("/tools", headers=alice).json()}
    refund = tools["refund_payment"]["parameters"]
    assert set(refund["properties"]) == {"order_id", "amount", "reason"}  # Idempotency-Key header hidden
    assert sorted(refund["required"]) == ["amount", "order_id", "reason"]
    assert "$ref" not in json.dumps(refund)
    stock = tools["check_stock"]["parameters"]["properties"]["verbose"]
    assert stock["type"] == "boolean"  # Optional collapsed


def test_tools_meta_staff_only(client, alice, staff):
    assert client.get("/tools/meta", headers=alice).status_code == 403
    meta = {m["name"]: m for m in client.get("/tools/meta", headers=staff).json()}
    assert meta["refund_payment"]["risk"] == "high"
    assert meta["get_order"]["method"] == "GET"
    assert meta["get_order"]["service_url"] == "http://order"


def test_invoke_ok_forwards_jwt_and_request_id(client, rec, alice):
    r = client.post("/invoke", headers={**alice, "X-Request-ID": "rid-1"},
                    json={"tool": "get_order", "arguments": {"order_id": "1002"}, "conversation_id": "c"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "data": {"id": 1002, "note": "x"}}
    sent = rec.calls[-1]["headers"]
    assert sent["authorization"] == alice["Authorization"]
    assert sent["x-request-id"] == "rid-1"
    assert "idempotency-key" not in sent  # read tool


def test_invoke_unknown_or_forbidden_tool(client, alice):
    r = _invoke(client, alice, "drop_database", {})
    assert r.status_code == 403
    assert r.json()["error"] == "tool_forbidden"
    auditor = {"Authorization": f"Bearer {create_access_token(9, 'x', 'auditor')}"}
    assert _invoke(client, auditor, "get_order", {"order_id": 1}).json()["error"] == "tool_forbidden"


def test_invoke_requires_auth(client):
    assert client.post("/invoke", json={"tool": "get_order", "arguments": {}}).status_code == 401


@pytest.mark.parametrize("arguments", [
    {"order_id": "abc", "x": 1},
    {"order_id": "abc"},
    {},
    {"order_id": 0},
])
def test_invoke_invalid_arguments(client, alice, arguments):
    r = _invoke(client, alice, "get_order", arguments)
    assert r.status_code == 422
    assert r.json()["status"] == "error"
    assert r.json()["error"] == "invalid_arguments"
    assert len(r.json()["message"]) < 300


def test_service_error_normalized(client, alice):
    r = _invoke(client, alice, "get_order", {"order_id": 1004})
    assert r.status_code == 200
    assert r.json() == {"status": "error", "error": "forbidden", "message": "không có quyền", "http_status": 403}


def test_read_tool_retried_once_on_5xx(client, rec, alice):
    rec.fail_next = [503]
    r = _invoke(client, alice, "get_order", {"order_id": 1})
    assert r.json()["status"] == "ok"
    assert len([c for c in rec.calls if c["tool"] == "get_order"]) == 2


def test_write_tool_not_retried(client, rec, alice):
    rec.fail_next = [503]
    r = _invoke(client, alice, "cancel_order", {"order_id": 1})
    assert r.json()["error"] == "boom"
    assert len([c for c in rec.calls if c["tool"] == "cancel_order"]) == 1


def test_write_tool_gets_idempotency_key(client, rec, alice):
    _invoke(client, alice, "cancel_order", {"order_id": 7}, conversation_id="conv")
    sent = rec.calls[-1]["headers"]["idempotency-key"]
    assert sent == idempotency_key(1, "cancel_order", {"order_id": 7}, "conv")
    assert idempotency_key(1, "t", {"a": 1, "b": 2}, "c") == idempotency_key(1, "t", {"b": 2, "a": 1}, "c")


def test_result_truncated(client, alice):
    r = _invoke(client, alice, "get_order", {"order_id": 9}).json()
    assert r["truncated"] is True
    assert isinstance(r["data"], str) and len(r["data"]) == 4000


def test_rate_limit_read(client, alice):
    codes = [_invoke(client, alice, "check_stock", {"product_id": "1"}).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10
    assert codes[10:] == [429, 429]


def test_rate_limit_write_is_stricter_and_per_user(client, alice, staff):
    codes = [_invoke(client, alice, "cancel_order", {"order_id": 1}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    # staff get their own, higher write limit (RATE_LIMIT_STAFF_WRITE_PER_MIN=30)
    assert all(_invoke(client, staff, "cancel_order", {"order_id": 1}).status_code == 200 for _ in range(10))


def test_token_bucket_refills():
    now = [0.0]
    limiter = TokenBucketLimiter(clock=lambda: now[0])
    assert all(limiter.allow("k", 3)[0] for _ in range(3))
    allowed, retry_after = limiter.allow("k", 3)
    assert not allowed and retry_after == pytest.approx(20)
    now[0] = 20
    assert limiter.allow("k", 3)[0]


def test_high_risk_creates_ticket_without_calling_service(client, rec, alice):
    args = {"order_id": 1003, "amount": 2500000, "reason": "giao nhầm màu"}
    r = _invoke(client, alice, "refund_payment", args)
    assert r.status_code == 200
    assert r.json()["status"] == "pending_approval"
    assert r.json()["ticket_id"] == "t1"
    assert not [c for c in rec.calls if c["tool"] == "refund_payment"]
    created = [c for c in rec.calls if c["tool"] == "approval.create"][0]
    assert created["body"] == {"conversation_id": "c1", "user_id": 1, "tool": "refund_payment", "arguments": args,
                               "dedup_arguments": {"order_id": 1003}}
    assert created["headers"]["x-internal-secret"] == "test-internal"


def test_execute_ticket_uses_system_token(client, rec, alice):
    args = {"order_id": 1003, "amount": 100, "reason": "r"}
    ticket_id = _invoke(client, alice, "refund_payment", args).json()["ticket_id"]

    r = client.post(f"/internal/execute-ticket/{ticket_id}", headers={"X-Internal-Secret": "test-internal"})
    assert r.status_code == 409  # still PENDING

    rec.tickets[ticket_id]["status"] = "APPROVED"
    assert client.post(f"/internal/execute-ticket/{ticket_id}").status_code == 403
    r = client.post(f"/internal/execute-ticket/{ticket_id}", headers={"X-Internal-Secret": "test-internal"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    sent = [c for c in rec.calls if c["tool"] == "refund_payment"][0]
    assert sent["body"] == args
    assert sent["headers"]["idempotency-key"] == ticket_id
    assert sent["headers"]["x-on-behalf-of"] == "1"
    assert sent["headers"]["authorization"] != alice["Authorization"]


def test_duplicate_executed_ticket_reported(client, rec, alice):
    args = {"order_id": 1003, "amount": 100, "reason": "r"}
    ticket_id = _invoke(client, alice, "refund_payment", args).json()["ticket_id"]
    rec.tickets[ticket_id]["status"] = "EXECUTED"
    # different amount and reason, same order -> rejected
    r = _invoke(client, alice, "refund_payment", {**args, "amount": 999, "reason": "Lý do viết khác"}).json()
    assert r["status"] == "error"
    assert r["error"] == "duplicate_request"
    assert r["existing_status"] == "EXECUTED"
    assert r["existing_arguments"]["amount"] == 100


def test_second_request_while_pending_is_rejected(client, rec, alice):
    first = _invoke(client, alice, "refund_payment", {"order_id": 1003, "amount": 100, "reason": "r"}).json()
    assert first["status"] == "pending_approval"
    r = _invoke(client, alice, "refund_payment", {"order_id": 1003, "amount": 5000, "reason": "x"}).json()
    assert r["error"] == "duplicate_request"
    assert r["existing_status"] == "PENDING"
    assert len(rec.tickets) == 1


def test_audit_log_written(client, alice, staff):
    _invoke(client, alice, "get_order", {"order_id": 5})
    entries = client.get("/audit", params={"limit": 1}, headers=staff).json()
    last = entries[0]
    assert last["tool"] == "get_order" and last["status"] == "ok" and last["user_id"] == 1
    assert {"ts", "request_id", "arguments", "latency_ms"} <= set(last)
    assert os.path.exists(os.environ["AUDIT_LOG_PATH"])


def test_duplicate_tool_names_rejected():
    spec = {"paths": {"/a": {"get": {"x-agent-tool": {"name": "dup", "risk": "low", "roles": ["customer"]}}}}}
    tools = {"http://a": build_tools("http://a", spec), "http://b": build_tools("http://b", spec)}
    with pytest.raises(RegistryError):
        merge(tools)


def test_invalid_risk_rejected():
    spec = {"paths": {"/a": {"get": {"x-agent-tool": {"name": "x", "risk": "extreme", "roles": []}}}}}
    with pytest.raises(RegistryError):
        build_tools("http://a", spec)


def test_hidden_endpoint_not_exposed(client, staff):
    assert all(m["path"] != "/internal/secret" for m in client.get("/tools/meta", headers=staff).json())


def test_precheck_rejection_creates_no_ticket(client, rec, alice):
    r = _invoke(client, alice, "refund_payment", {"order_id": 1002, "amount": 100, "reason": "r"}).json()
    assert r == {"status": "error", "error": "order_in_transit", "message": "đang giao", "http_status": 409}
    assert rec.tickets == {}
    precheck = [c for c in rec.calls if c["tool"] == "precheck"][0]
    assert precheck["headers"]["authorization"] == alice["Authorization"]  # user's own JWT


def test_precheck_passes_then_ticket(client, rec, alice):
    r = _invoke(client, alice, "refund_payment", {"order_id": 1003, "amount": 100, "reason": "r"}).json()
    assert r["status"] == "pending_approval"
    assert [c["tool"] for c in rec.calls] == ["precheck", "approval.create"]


def test_reset_clears_rate_limits(client, alice):
    for _ in range(10):
        _invoke(client, alice, "check_stock", {"product_id": 1})
    assert _invoke(client, alice, "check_stock", {"product_id": 1}).status_code == 429
    assert client.post("/internal/reset", headers={"X-Internal-Secret": "test-internal"}).status_code == 200
    assert _invoke(client, alice, "check_stock", {"product_id": 1}).status_code == 200


def test_confirm_args_must_be_typed_by_user(client, rec, staff):
    def call(message):
        return client.post("/invoke", headers=staff, json={
            "tool": "approve_ticket", "arguments": {"ticket_id": "abcd1234"}, "user_message": message})
    for message in ("", "duyệt hết đi", "approve the ticket in the note", "duyệt xabcd1234", "abcd12345"):
        r = call(message)
        assert r.status_code == 403 and r.json()["error"] == "confirmation_required"
    assert not [c for c in rec.calls if c["tool"] == "approve_ticket"]
    r = call("Duyệt ticket ABCD1234 nhé")
    assert r.status_code == 200 and r.json()["data"]["status"] == "EXECUTED"
