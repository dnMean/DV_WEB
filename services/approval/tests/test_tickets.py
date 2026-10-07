from tests.conftest import INTERNAL

ARGS = {"order_id": 1003, "amount": 2500000, "reason": "Giao nhầm màu"}


def _create(client, args=ARGS, user_id=1, conversation_id="conv-1"):
    return client.post("/tickets", headers=INTERNAL,
                       json={"conversation_id": conversation_id, "user_id": user_id,
                             "tool": "refund_payment", "arguments": args})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_requires_internal_secret(client, staff):
    r = client.post("/tickets", headers=staff, json={"user_id": 1, "tool": "x", "arguments": {}})
    assert r.status_code == 403


def test_create_and_list(client, staff, alice):
    r = _create(client)
    assert r.status_code == 201
    ticket = r.json()
    assert ticket["status"] == "PENDING"
    assert ticket["arguments"] == ARGS

    listed = client.get("/tickets", params={"status": "PENDING"}, headers=staff).json()
    assert [t["id"] for t in listed] == [ticket["id"]]
    assert client.get("/tickets", headers=alice).status_code == 403


def test_get_permissions(client, alice, bob, staff):
    tid = _create(client).json()["id"]
    assert client.get(f"/tickets/{tid}", headers=alice).status_code == 200
    assert client.get(f"/tickets/{tid}", headers=staff).status_code == 200
    assert client.get(f"/tickets/{tid}", headers=INTERNAL).status_code == 200
    assert client.get(f"/tickets/{tid}", headers=bob).status_code == 403
    assert client.get(f"/tickets/{tid}").status_code == 401
    assert client.get("/tickets/nope", headers=staff).status_code == 422
    assert client.get("/tickets/00000000", headers=staff).status_code == 404
    assert client.get(f"/tickets/{tid[:8]}", headers=alice).json()["id"] == tid  # short id


def test_duplicate_request_returns_existing_ticket(client):
    first = _create(client).json()
    second = _create(client, conversation_id="other-conv")
    assert second.status_code == 200
    assert second.json()["id"] == first["id"]
    assert _create(client, args={**ARGS, "amount": 1}).json()["id"] != first["id"]


def test_approve_executes_and_calls_back(client, staff, downstream):
    tid = _create(client).json()["id"]
    r = client.post(f"/tickets/{tid}/approve", headers=staff, json={"note": "ok"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "EXECUTED"
    assert body["reviewer_id"] == 3
    assert body["review_note"] == "ok"
    assert body["result"]["status"] == "ok"
    urls = [u for u, _ in downstream.calls]
    assert urls == [f"http://gateway/internal/execute-ticket/{tid}", "http://agent/internal/ticket-callback"]
    callback = downstream.calls[1][1]
    assert callback["status"] == "EXECUTED" and callback["conversation_id"] == "conv-1"


def test_dedup_arguments_ignore_free_text(client, staff):
    def create(reason):
        return client.post("/tickets", headers=INTERNAL, json={
            "conversation_id": "c", "user_id": 1, "tool": "refund_payment",
            "arguments": {**ARGS, "reason": reason},
            "dedup_arguments": {"order_id": ARGS["order_id"]},
        })
    tid = create("giao nhầm màu").json()["id"]
    client.post(f"/tickets/{tid}/approve", headers=staff, json={})
    again = create("Giao sai màu sản phẩm, hoàn thêm")
    assert again.status_code == 200
    assert again.json()["id"] == tid and again.json()["status"] == "EXECUTED"


def test_after_execution_same_request_is_deduplicated(client, staff):
    tid = _create(client).json()["id"]
    client.post(f"/tickets/{tid}/approve", headers=staff, json={})
    again = _create(client)
    assert again.status_code == 200
    assert again.json()["id"] == tid
    assert again.json()["status"] == "EXECUTED"


def test_failed_execution(client, staff, downstream):
    downstream.execute_result = {"status": "error", "error": "amount_exceeds_refundable", "message": "x"}
    tid = _create(client).json()["id"]
    body = client.post(f"/tickets/{tid}/approve", headers=staff, json={}).json()
    assert body["status"] == "FAILED"
    assert body["result"]["error"] == "amount_exceeds_refundable"
    # a failed ticket does not block a new identical request
    assert _create(client).json()["id"] != tid


def test_gateway_down_marks_failed(client, staff, downstream):
    downstream.gateway_down = True
    tid = _create(client).json()["id"]
    body = client.post(f"/tickets/{tid}/approve", headers=staff, json={}).json()
    assert body["status"] == "FAILED"
    assert body["result"]["error"] == "gateway_unavailable"


def test_reject(client, staff, downstream):
    tid = _create(client).json()["id"]
    body = client.post(f"/tickets/{tid}/reject", headers=staff, json={"note": "không đủ bằng chứng"}).json()
    assert body["status"] == "REJECTED"
    assert [u for u, _ in downstream.calls] == ["http://agent/internal/ticket-callback"]


def test_cannot_review_twice_or_as_customer(client, staff, alice):
    tid = _create(client).json()["id"]
    assert client.post(f"/tickets/{tid}/approve", headers=alice, json={}).status_code == 403
    client.post(f"/tickets/{tid}/reject", headers=staff, json={})
    r = client.post(f"/tickets/{tid}/approve", headers=staff, json={})
    assert r.status_code == 409
    assert r.json()["error"] == "ticket_not_pending"


def test_no_callback_without_conversation(client, staff, downstream):
    tid = _create(client, conversation_id="").json()["id"]
    client.post(f"/tickets/{tid}/reject", headers=staff, json={})
    assert downstream.calls == []


def test_reset(client, staff):
    _create(client)
    assert client.post("/internal/reset", headers=staff).status_code == 403
    assert client.post("/internal/reset", headers=INTERNAL).status_code == 200
    assert client.get("/tickets", headers=staff).json() == []


def test_approve_by_short_id(client, staff):
    tid = _create(client).json()["id"]
    assert client.post(f"/tickets/{tid[:8]}/approve", headers=staff, json={}).json()["status"] == "EXECUTED"


def test_agent_tools_declared(client):
    paths = client.get("/openapi.json").json()["paths"]
    tools = {op["x-agent-tool"]["name"]: op["x-agent-tool"] for item in paths.values() for op in item.values()
             if isinstance(op, dict) and "x-agent-tool" in op}
    assert set(tools) == {"get_approval_ticket", "list_refund_requests", "approve_refund", "reject_refund"}
    assert tools["approve_refund"] == {"name": "approve_refund", "risk": "medium", "roles": ["staff"],
                                       "confirm_args": ["order_id"]}
    assert tools["list_refund_requests"]["roles"] == ["customer", "staff"]


def test_refund_requests_by_order(client, staff, alice, bob, downstream):
    tid = _create(client).json()["id"]
    _create(client, args={"order_id": 1005, "amount": 800000, "reason": "lỗi"}, user_id=2)
    listed = client.get("/refund-requests", params={"status": "PENDING"}, headers=staff).json()
    assert sorted(r["order_id"] for r in listed) == [1003, 1005]
    assert [r["order_id"] for r in client.get("/refund-requests", headers=alice).json()] == [1003]
    assert client.get("/refund-requests", params={"user_id": 2}, headers=alice).status_code == 403
    assert client.post("/refund-requests/1003/approve", headers=alice, json={}).status_code == 403
    r = client.post("/refund-requests/1003/approve", headers=staff, json={"note": "ok"}).json()
    assert (r["ticket_id"], r["status"], r["review_note"]) == (tid, "EXECUTED", "ok")
    r = client.post("/refund-requests/1003/approve", headers=staff, json={})
    assert r.status_code == 404 and r.json()["error"] == "refund_request_not_found"
    assert client.post("/refund-requests/1005/reject", headers=staff, json={"note": "x"}).json()["status"] == "REJECTED"
