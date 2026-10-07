"""Use cases from docs/USECASES.md, run against the whole stack (no LLM involved)."""
import time

from conftest import eventually

ALICE_ORDERS = {1001: "DELIVERED", 1002: "SHIPPING", 1003: "PAID"}
BOB_ORDERS = {1004: "PENDING", 1005: "PAID"}
EXPECTED = {  # order status -> (payment status or None, shipment status or None)
    "PENDING": (None, None),
    "PAID": ("SUCCESS", "WAITING_PICKUP"),
    "SHIPPING": ("SUCCESS", "IN_TRANSIT"),
    "DELIVERED": ("SUCCESS", "DELIVERED"),
}


def full_refund(order_id: int, amount: int, reason: str = "giao nhầm màu") -> dict:
    return {"order_id": order_id, "amount": amount, "reason": reason}


def request_and_approve(api, user, args) -> dict:
    created = api.invoke(user, "refund_payment", args)
    assert created["status"] == "pending_approval", created
    return api.approve(created["ticket_id"])


# ------------------------------------------------------------------ lookup / authorization

def test_uc01_seed_is_consistent(api):
    for order_id, status in {**ALICE_ORDERS, **BOB_ORDERS}.items():
        order = api.order(order_id)
        assert order["status"] == status
        assert order["total"] == sum(i["qty"] * i["price"] for i in order["items"])
        pay_status, ship_status = EXPECTED[status]
        pay = api.get("payment", "/payments", params={"order_id": order_id})
        ship = api.shipment(order_id)
        if pay_status is None:
            assert pay.status_code == 404 and ship.status_code == 404
        else:
            assert pay.json()["status"] == pay_status
            assert pay.json()["amount"] == order["total"]
            assert pay.json()["user_id"] == order["user_id"]
            assert ship.json()["status"] == ship_status
            assert ship.json()["user_id"] == order["user_id"]


def test_uc02_customer_reads_own_data(api):
    for tool, args in (("get_order", {"order_id": 1002}), ("get_payment", {"order_id": 1002}),
                       ("get_shipment", {"order_id": 1002})):
        r = api.invoke("alice", tool, args)
        assert r["status"] == "ok", (tool, r)
    listed = api.invoke("alice", "list_my_orders", {})
    assert sorted(o["id"] for o in listed["data"]["orders"]) == [1001, 1002, 1003]
    assert listed["data"]["total"] == 3


def test_uc03_customer_cannot_read_others(api):
    for tool in ("get_order", "get_payment", "get_shipment"):
        r = api.invoke("alice", tool, {"order_id": 1005})
        assert r["status"] == "error" and r["error"] == "forbidden", (tool, r)
        assert "data" not in r


def test_uc04_staff_reads_everything(api):
    for order_id in (1001, 1005):
        assert api.invoke("staff1", "get_order", {"order_id": order_id})["status"] == "ok"


def _ids(r):
    assert r["status"] == "ok", r
    assert r["data"]["total"] == len(r["data"]["orders"]), r  # all results fit in one page here
    return sorted(o["id"] for o in r["data"]["orders"])


def test_uc05_staff_searches_orders(api):
    assert _ids(api.invoke("staff1", "search_orders", {})) == [1001, 1002, 1003, 1004, 1005]
    assert _ids(api.invoke("staff1", "search_orders", {"user_id": 2})) == [1004, 1005]
    assert _ids(api.invoke("staff1", "search_orders", {"order_id": 1003})) == [1003]
    assert _ids(api.invoke("staff1", "search_orders", {"status": "SHIPPING"})) == [1002]
    assert _ids(api.invoke("staff1", "search_orders", {"status": "DELIVERED", "user_id": 1})) == [1001]
    assert _ids(api.invoke("staff1", "search_orders", {"refunded": True})) == []
    request_and_approve(api, "alice", full_refund(1001, 100_000))  # partial, stays DELIVERED
    request_and_approve(api, "alice", full_refund(1003, 2_500_000))
    eventually(lambda: _eq(_ids(api.invoke("staff1", "search_orders", {"refunded": True})), [1001, 1003]))
    assert _ids(api.invoke("staff1", "search_orders", {"status": "REFUNDED"})) == [1003]


def test_uc06_order_listing_tools_per_role(api):
    assert api.invoke("alice", "search_orders", {})["error"] == "tool_forbidden"
    assert api.invoke("staff1", "list_my_orders", {})["error"] == "tool_forbidden"


def test_uc07_generated_demo_data_is_consistent(api):
    from conftest import INTERNAL, RESETTABLE, URL
    for name in RESETTABLE:
        assert api.http.post(f"{URL[name]}/internal/reset", params={"extra_orders": 100}, headers=INTERNAL).status_code == 200
    orders = api.get("order", "/orders/search", params={"limit": 200}).json()["orders"]
    assert len(orders) == 105
    shipments = {s["order_id"]: s for s in api.get("shipping", "/shipments").json()}
    tickets = api.get("approval", "/tickets", params={"limit": 200}).json()
    for o in orders:
        pay = api.get("payment", "/payments", params={"order_id": o["id"]})
        ship = shipments.get(o["id"])
        mine = [t for t in tickets if t["arguments"]["order_id"] == o["id"]]
        ctx = (o, pay.json(), ship and ship["status"], mine)
        assert all(t["user_id"] == o["user_id"] for t in mine), ctx
        assert sum(t["arguments"]["amount"] for t in mine if t["status"] == "EXECUTED") == o["refunded_amount"], ctx
        pending = [t for t in mine if t["status"] == "PENDING"]
        assert len(pending) <= 1, ctx
        if o["status"] in ("PENDING", "CANCELLED"):
            assert pay.status_code == 404 and ship is None and not mine, ctx
            continue
        p = pay.json()
        assert (p["amount"], p["user_id"]) == (o["total"], o["user_id"]), ctx
        assert sum(r["amount"] for r in p["refunds"]) == o["refunded_amount"], ctx
        assert ship["user_id"] == o["user_id"], ctx
        expected = {
            "PAID": ({"SUCCESS"}, {"WAITING_PICKUP"}),
            "SHIPPING": ({"SUCCESS"}, {"IN_TRANSIT"}),
            "DELIVERED": ({"SUCCESS", "PARTIALLY_REFUNDED"}, {"DELIVERED"}),
            "REFUNDED": ({"REFUNDED"}, {"CANCELLED", "DELIVERED"}),
        }[o["status"]]
        assert p["status"] in expected[0] and ship["status"] in expected[1], ctx
        assert (p["status"] == "PARTIALLY_REFUNDED") == (o["status"] == "DELIVERED" and o["refunded_amount"] > 0), ctx
        if pending:
            assert o["status"] in ("PAID", "DELIVERED"), ctx
            if o["status"] == "PAID":
                assert pending[0]["arguments"]["amount"] == o["total"], ctx


# ------------------------------------------------------------------ cancel

def test_uc10_cancel_pending_restocks(api):
    before = {p: api.stock(p) for p in (4, 5, 6)}
    r = api.invoke("bob", "cancel_order", {"order_id": 1004})
    assert r["status"] == "ok" and r["data"]["status"] == "CANCELLED"
    eventually(lambda: _eq([api.stock(p) for p in (4, 5, 6)], [before[p] + 1 for p in (4, 5, 6)]))


def test_uc11_cancel_twice_restocks_once(api):
    before = api.stock(4)
    api.invoke("bob", "cancel_order", {"order_id": 1004})
    eventually(lambda: _eq(api.stock(4), before + 1))
    again = api.post("order", "/orders/1004/cancel", "bob")
    assert again.status_code == 200 and again.json()["status"] == "CANCELLED"
    time.sleep(1)
    assert api.stock(4) == before + 1


def test_uc12_cancel_paid_rejected(api):
    r = api.invoke("alice", "cancel_order", {"order_id": 1003})
    assert r["error"] == "order_already_paid" and r["suggested_tool"] == "refund_payment"
    assert api.order(1003)["status"] == "PAID"
    assert api.shipment(1003).json()["status"] == "WAITING_PICKUP"


def test_uc13_cancel_shipping_rejected(api):
    r = api.invoke("alice", "cancel_order", {"order_id": 1002})
    assert r["status"] == "error" and r["http_status"] == 409
    assert api.order(1002)["status"] == "SHIPPING"


# ------------------------------------------------------------------ refunds

def test_uc20_refund_paid_order_full(api):
    stock_before = api.stock(1)
    chat = api.post("agent", "/chat", "alice", {"message": "Xin chào"}).json()
    conv = chat["conversation_id"]
    created = api.invoke("alice", "refund_payment", full_refund(1003, 2_500_000), conversation_id=conv)
    assert created["status"] == "pending_approval"
    # nothing happens before approval
    assert api.payment(1003)["status"] == "SUCCESS"
    assert api.order(1003)["status"] == "PAID"

    ticket = api.approve(created["ticket_id"])
    assert ticket["status"] == "EXECUTED", ticket
    assert api.payment(1003)["status"] == "REFUNDED"
    assert api.shipment(1003).json()["status"] == "CANCELLED"
    eventually(lambda: _eq(api.order(1003)["status"], "REFUNDED"))
    assert api.order(1003)["refunded_amount"] == 2_500_000
    eventually(lambda: _eq(api.stock(1), stock_before + 1))
    messages = api.get("agent", f"/conversations/{conv}", "alice").json()["messages"]
    assert messages[-1]["kind"] == "notification" and "đã được duyệt và thực hiện" in messages[-1]["content"]


def test_uc21_partial_refund_before_shipping_rejected(api):
    r = api.invoke("alice", "refund_payment", full_refund(1003, 500_000))
    assert r["status"] == "error" and r["error"] == "full_refund_required", r
    assert api.tickets() == []


def test_uc22_refund_in_transit_rejected(api):
    r = api.invoke("alice", "refund_payment", full_refund(1002, 1_200_000))
    assert r["error"] == "order_in_transit", r
    assert api.tickets() == []


def test_uc23_partial_refund_after_delivery(api):
    stock_before = api.stock(3)
    ticket = request_and_approve(api, "alice", full_refund(1001, 100_000, "trầy xước"))
    assert ticket["status"] == "EXECUTED", ticket
    assert api.payment(1001)["status"] == "PARTIALLY_REFUNDED"
    eventually(lambda: _eq(api.order(1001)["refunded_amount"], 100_000))
    assert api.order(1001)["status"] == "DELIVERED"
    assert api.shipment(1001).json()["status"] == "DELIVERED"
    assert api.stock(3) == stock_before


def test_uc24_full_refund_after_delivery(api):
    stock_before = api.stock(3)
    ticket = request_and_approve(api, "alice", full_refund(1001, 350_000, "hỏng"))
    assert ticket["status"] == "EXECUTED", ticket
    assert api.payment(1001)["status"] == "REFUNDED"
    eventually(lambda: _eq(api.order(1001)["status"], "REFUNDED"))
    assert api.shipment(1001).json()["status"] == "DELIVERED"
    assert api.stock(3) == stock_before


def test_uc25_repeat_after_executed(api):
    request_and_approve(api, "alice", full_refund(1003, 2_500_000))
    for amount in (2_500_000, 100_000):  # 3 refund calls total = the per-minute write limit
        r = api.invoke("alice", "refund_payment", full_refund(1003, amount, "hoàn thêm"))
        assert r["status"] == "error" and r["error"] in ("duplicate_request", "order_not_refundable"), r
    assert len(api.tickets()) == 1
    assert len(api.payment(1003)["refunds"]) == 1


def test_uc26_repeat_while_pending(api):
    first = api.invoke("alice", "refund_payment", full_refund(1001, 100_000))
    assert first["status"] == "pending_approval"
    r = api.invoke("alice", "refund_payment", full_refund(1001, 200_000, "khác"))
    assert r["error"] == "duplicate_request" and r["existing_status"] == "PENDING"
    assert len(api.tickets()) == 1


def test_uc27_amount_over_paid_rejected(api):
    r = api.invoke("alice", "refund_payment", full_refund(1001, 9_999_999))
    assert r["error"] == "amount_exceeds_refundable", r
    assert api.tickets() == []


def test_uc28_refund_unpaid_rejected(api):
    r = api.invoke("bob", "refund_payment", full_refund(1004, 450_000))
    assert r["error"] in ("order_not_paid", "payment_not_found"), r
    assert api.tickets() == []


def test_uc29_refund_other_users_order_rejected(api):
    r = api.invoke("alice", "refund_payment", full_refund(1005, 800_000))
    assert r["error"] == "forbidden", r
    assert api.tickets() == []


def test_uc30_rejected_ticket_allows_new_request(api):
    first = api.invoke("alice", "refund_payment", full_refund(1003, 2_500_000))
    assert api.reject(first["ticket_id"], "thiếu ảnh")["status"] == "REJECTED"
    assert api.payment(1003)["status"] == "SUCCESS"
    assert api.order(1003)["status"] == "PAID"
    second = api.invoke("alice", "refund_payment", full_refund(1003, 2_500_000))
    assert second["status"] == "pending_approval" and second["ticket_id"] != first["ticket_id"]


def test_uc31_state_changed_before_approval(api):
    created = api.invoke("alice", "refund_payment", full_refund(1003, 2_500_000))
    assert created["status"] == "pending_approval"
    assert api.advance(1003, "IN_TRANSIT").status_code == 200
    eventually(lambda: _eq(api.order(1003)["status"], "SHIPPING"))
    ticket = api.approve(created["ticket_id"])
    assert ticket["status"] == "FAILED", ticket
    assert ticket["result"]["error"] == "order_in_transit"
    assert api.payment(1003)["refunds"] == []
    assert api.shipment(1003).json()["status"] == "IN_TRANSIT"


def test_uc32_customer_cannot_call_refund_directly(api):
    r = api.post("payment", "/refunds", "alice", full_refund(1003, 2_500_000), headers={"Idempotency-Key": "x"})
    assert r.status_code == 403


def test_uc33_execute_idempotent(api):
    stock_before = api.stock(1)
    body = full_refund(1003, 2_500_000)
    r1 = api.post("payment", "/refunds", "staff1", body, headers={"Idempotency-Key": "same-key"})
    r2 = api.post("payment", "/refunds", "staff1", body, headers={"Idempotency-Key": "same-key"})
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r2.json()["replayed"] is True
    assert len(api.payment(1003)["refunds"]) == 1
    eventually(lambda: _eq(api.stock(1), stock_before + 1))
    time.sleep(1)
    assert api.stock(1) == stock_before + 1


def test_uc34_bob_refund_paid_order(api):
    stock_before = api.stock(7)
    ticket = request_and_approve(api, "bob", full_refund(1005, 800_000, "lỗi"))
    assert ticket["status"] == "EXECUTED", ticket
    assert api.shipment(1005).json()["status"] == "CANCELLED"
    eventually(lambda: _eq(api.order(1005)["status"], "REFUNDED"))
    eventually(lambda: _eq(api.stock(7), stock_before + 1))


def test_uc35_check_refund_eligibility(api):
    def check(user, order_id):
        return api.invoke(user, "check_refund_eligibility", {"order_id": order_id})

    r = check("alice", 1002)
    assert r["status"] == "ok" and r["data"]["eligible"] is False and r["data"]["reason"] == "order_in_transit", r
    r = check("alice", 1003)["data"]
    assert (r["eligible"], r["full_refund_required"], r["max_refundable"]) == (True, True, 2_500_000)
    r = check("alice", 1001)["data"]
    assert (r["eligible"], r["full_refund_required"], r["max_refundable"]) == (True, False, 350_000)
    assert check("bob", 1004)["data"]["reason"] == "order_not_paid"
    assert check("alice", 1005)["error"] == "forbidden"
    request_and_approve(api, "alice", full_refund(1003, 2_500_000))
    eventually(lambda: _eq(check("alice", 1003)["data"]["reason"], "order_not_refundable"))
    assert api.tickets()[0]["status"] == "EXECUTED" and len(api.tickets()) == 1


# ------------------------------------------------------------------ shipping

NEW_ADDRESS = {"order_id": 1003, "address": "12 Lê Lợi, Quận 1, TP.HCM"}


def test_uc40_update_address_waiting_pickup(api):
    r = api.invoke("alice", "update_shipping_address", NEW_ADDRESS)
    assert r["status"] == "ok" and r["data"]["address"] == NEW_ADDRESS["address"]


def test_uc41_update_address_in_transit_rejected(api):
    r = api.invoke("alice", "update_shipping_address", {**NEW_ADDRESS, "order_id": 1002})
    assert r["error"] == "shipment_not_editable"


def test_uc42_update_address_after_refund_rejected(api):
    request_and_approve(api, "alice", full_refund(1003, 2_500_000))
    r = api.invoke("alice", "update_shipping_address", NEW_ADDRESS)
    assert r["error"] == "shipment_not_editable"


def test_uc43_shipping_progress_updates_order(api):
    assert api.advance(1003, "IN_TRANSIT").status_code == 200
    eventually(lambda: _eq(api.order(1003)["status"], "SHIPPING"))
    assert api.invoke("alice", "refund_payment", full_refund(1003, 100_000))["error"] == "order_in_transit"
    assert api.advance(1003, "DELIVERED").status_code == 200
    eventually(lambda: _eq(api.order(1003)["status"], "DELIVERED"))
    ticket = request_and_approve(api, "alice", full_refund(1003, 100_000, "móp hộp"))
    assert ticket["status"] == "EXECUTED"


def test_uc44_invalid_shipment_transition(api):
    request_and_approve(api, "alice", full_refund(1003, 2_500_000))
    assert api.advance(1003, "IN_TRANSIT").status_code == 409  # cancelled shipment
    assert api.advance(1001, "IN_TRANSIT").status_code == 409  # delivered -> backwards
    assert api.post("shipping", "/shipments/1002/advance", "alice",
                    {"status": "DELIVERED", "location": "x", "description": "x"}).status_code == 403


def _staff_says(api, tool, arguments, message):
    r = api.post("gateway", "/invoke", "staff1", {"tool": tool, "arguments": arguments, "conversation_id": "e2e",
                                                  "user_message": message})
    return {**r.json(), "_http": r.status_code}


def test_uc45_staff_updates_shipment_by_chat(api):
    r = _staff_says(api, "update_shipment_status", {"order_id": 1003, "status": "IN_TRANSIT"}, "đơn 1003 đã được lấy hàng")
    assert r["status"] == "ok" and r["data"]["status"] == "IN_TRANSIT", r
    eventually(lambda: _eq(api.order(1003)["status"], "SHIPPING"))
    r = _staff_says(api, "update_shipment_status", {"order_id": 1003, "status": "IN_TRANSIT", "location": "Kho Hà Nội"},
                    "đơn 1003 đang ở kho Hà Nội")
    assert r["data"]["events"][-1]["location"] == "Kho Hà Nội"


def test_uc46_staff_marks_delivered_by_chat(api):
    r = _staff_says(api, "update_shipment_status", {"order_id": 1002, "status": "DELIVERED"}, "Đơn 1002 đã giao xong")
    assert r["status"] == "ok" and r["data"]["status"] == "DELIVERED", r
    eventually(lambda: _eq(api.order(1002)["status"], "DELIVERED"))
    assert api.invoke("alice", "refund_payment", full_refund(1002, 100_000))["status"] == "pending_approval"


def test_uc47_invalid_status_change_by_chat(api):
    r = _staff_says(api, "update_shipment_status", {"order_id": 1001, "status": "IN_TRANSIT"}, "đơn 1001 đang giao lại")
    assert r["error"] == "invalid_transition", r
    r = _staff_says(api, "update_shipment_status", {"order_id": 1004, "status": "IN_TRANSIT"}, "đơn 1004 lấy hàng")
    assert r["error"] == "shipment_not_found", r
    assert api.order(1001)["status"] == "DELIVERED" and api.order(1004)["status"] == "PENDING"


def test_uc48_status_change_requires_order_id(api):
    for message in ("giao hết các đơn đi", "đơn 10030 đã lấy hàng", ""):
        r = _staff_says(api, "update_shipment_status", {"order_id": 1003, "status": "IN_TRANSIT"}, message)
        assert r["_http"] == 403 and r["error"] == "confirmation_required", (message, r)
    assert api.shipment(1003).json()["status"] == "WAITING_PICKUP"


def test_uc49_status_change_permissions(api):
    assert "update_shipment_status" not in {t["function"]["name"] for t in api.get("gateway", "/tools", "alice").json()}
    r = api.post("gateway", "/invoke", "alice", {"tool": "update_shipment_status",
                                                 "arguments": {"order_id": 1003, "status": "IN_TRANSIT"},
                                                 "user_message": "đơn 1003 đã lấy hàng"}).json()
    assert r["error"] == "tool_forbidden"
    before = api.stock(4)
    r = _staff_says(api, "cancel_order", {"order_id": 1004}, "huỷ đơn 1004 giúp khách")
    assert r["status"] == "ok" and r["data"]["status"] == "CANCELLED", r
    eventually(lambda: _eq(api.stock(4), before + 1))


# ------------------------------------------------------------------ helpers

def _eq(actual, expected):
    assert actual == expected, f"{actual!r} != {expected!r}"
    return actual


# ------------------------------------------------------------------ staff: refund review via chat

def _pending_refund(api, user="alice", order_id=1001, amount=100_000):
    created = api.invoke(user, "refund_payment", full_refund(order_id, amount))
    assert created["status"] == "pending_approval", created
    return created["ticket_id"]


def _invoke_as(api, user, tool, arguments, user_message):
    r = api.post("gateway", "/invoke", user, {"tool": tool, "arguments": arguments, "conversation_id": "e2e",
                                              "user_message": user_message})
    return {**r.json(), "_http": r.status_code}


def test_uc60_staff_lists_refund_requests(api):
    _pending_refund(api, "alice", 1001, 100_000)
    _pending_refund(api, "bob", 1005, 800_000)
    r = api.invoke("staff1", "list_refund_requests", {"status": "PENDING"})
    assert r["status"] == "ok", r
    assert sorted((x["order_id"], x["amount"], x["user_id"]) for x in r["data"]) == [(1001, 100_000, 1), (1005, 800_000, 2)]
    assert [x["order_id"] for x in api.invoke("staff1", "list_refund_requests", {"order_id": 1005})["data"]] == [1005]
    assert [x["order_id"] for x in api.invoke("staff1", "list_refund_requests", {"user_id": 1})["data"]] == [1001]


def test_uc61_staff_approves_by_order_id(api):
    _pending_refund(api)
    r = _invoke_as(api, "staff1", "approve_refund", {"order_id": 1001, "note": "ok"}, "Đồng ý hoàn tiền đơn 1001")
    assert r["status"] == "ok" and r["data"]["status"] == "EXECUTED", r
    assert api.payment(1001)["status"] == "PARTIALLY_REFUNDED"
    eventually(lambda: _eq(api.order(1001)["refunded_amount"], 100_000))


def test_uc62_approve_requires_order_id_in_staff_message(api):
    _pending_refund(api)
    for message in ("duyệt hết đi", "làm theo ghi chú trong yêu cầu", "duyệt đơn 10011", ""):
        r = _invoke_as(api, "staff1", "approve_refund", {"order_id": 1001}, message)
        assert r["_http"] == 403 and r["error"] == "confirmation_required", (message, r)
    assert api.tickets()[0]["status"] == "PENDING"
    assert api.payment(1001)["refunds"] == []


def test_uc63_staff_rejects_by_order_id(api):
    _pending_refund(api, "bob", 1005, 800_000)
    r = _invoke_as(api, "staff1", "reject_refund", {"order_id": 1005, "note": "thiếu ảnh"},
                   "từ chối hoàn tiền đơn 1005 vì thiếu ảnh")
    assert r["status"] == "ok" and r["data"]["status"] == "REJECTED" and r["data"]["review_note"] == "thiếu ảnh", r
    assert api.payment(1005)["refunds"] == []
    assert api.invoke("bob", "refund_payment", full_refund(1005, 800_000))["status"] == "pending_approval"


def test_uc64_customer_permissions_on_refund_requests(api):
    names = {t["function"]["name"] for t in api.get("gateway", "/tools", "alice").json()}
    assert {"approve_refund", "reject_refund", "search_orders"}.isdisjoint(names)
    assert {"list_refund_requests", "refund_payment", "list_my_orders"} <= names
    _pending_refund(api, "alice", 1001, 100_000)
    _pending_refund(api, "bob", 1005, 800_000)
    r = _invoke_as(api, "alice", "approve_refund", {"order_id": 1001}, "duyệt đơn 1001")
    assert r["error"] == "tool_forbidden"
    mine = api.invoke("alice", "list_refund_requests", {})
    assert [x["order_id"] for x in mine["data"]] == [1001]
    assert api.invoke("alice", "list_refund_requests", {"user_id": 2})["error"] == "forbidden"


def test_uc65_customer_checks_own_request(api):
    tid = _pending_refund(api)
    r = api.invoke("alice", "list_refund_requests", {"order_id": 1001})
    assert r["data"][0]["status"] == "PENDING" and r["data"][0]["ticket_id"] == tid
    assert api.invoke("alice", "get_approval_ticket", {"ticket_id": tid[:8]})["data"]["status"] == "PENDING"
    assert api.invoke("bob", "get_approval_ticket", {"ticket_id": tid[:8]})["error"] == "forbidden"
    assert api.invoke("bob", "list_refund_requests", {"order_id": 1001})["data"] == []


def test_uc66_approve_without_pending_request(api):
    r = _invoke_as(api, "staff1", "approve_refund", {"order_id": 1003}, "duyệt đơn 1003")
    assert r["error"] == "refund_request_not_found", r


def test_uc67_staff_cannot_create_refund_request(api):
    assert api.invoke("staff1", "refund_payment", full_refund(1001, 100_000))["error"] == "tool_forbidden"


# ------------------------------------------------------------------ customer: products and ordering via chat

BOB_DELIVERY = {"recipient_name": "Trần Văn Bob", "recipient_phone": "0912345678",
                "address": "12 Lê Lợi, Quận 1, TP.HCM"}


def _quote(api, user="bob", items=None):
    r = api.invoke(user, "quote_order", {"items": items or [{"product_id": 3, "qty": 2}], **BOB_DELIVERY})
    assert r["status"] == "ok", r
    return r["data"]


def _place(api, user, code, message=None):
    return _invoke_as(api, user, "place_order", {"quote_id": code}, f"xác nhận {code}" if message is None else message)


def _placed_order(api, user="bob", items=None) -> dict:
    code = _quote(api, user, items)["quote_id"]
    r = _place(api, user, code)
    assert r["status"] == "ok", r
    return r["data"]["order"]


def test_uc70_customer_asks_about_products(api):
    found = api.invoke("bob", "search_products", {"q": "sac"})
    assert found["status"] == "ok" and {p["id"] for p in found["data"]} >= {3, 8}
    assert api.invoke("bob", "check_stock", {"product_id": 8})["data"]["in_stock"] is False
    assert api.invoke("bob", "get_product", {"product_id": 3})["data"]["price"] == 350_000


def test_uc71_quote_does_not_touch_stock(api):
    before = api.stock(3)
    quote = _quote(api, items=[{"product_id": 3, "qty": 2}, {"product_id": 4, "qty": 1}])
    assert len(quote["quote_id"]) == 6 and quote["total"] == 2 * 350_000 + 150_000
    assert quote["address"] == BOB_DELIVERY["address"]
    assert api.stock(3) == before
    assert api.get("order", "/orders", "bob").json()["total"] == 2  # no order yet


def test_uc72_place_requires_quote_code_in_customer_message(api):
    code = _quote(api)["quote_id"]
    for message in ("ok đặt đi", "xác nhận", f"xác nhận {code}X", ""):
        r = _place(api, "bob", code, message)
        assert r["_http"] == 403 and r["error"] == "confirmation_required", (message, r)
    assert api.get("order", "/orders", "bob").json()["total"] == 2


def test_uc73_place_order_reserves_stock_once(api):
    before = api.stock(3)
    code = _quote(api)["quote_id"]
    first = _place(api, "bob", code)
    assert first["status"] == "ok", first
    order = first["data"]["order"]
    assert order["status"] == "PENDING" and order["total"] == 700_000 and order["id"] > 1005
    again = _place(api, "bob", code.lower())
    assert again["data"]["order"]["id"] == order["id"]
    assert api.stock(3) == before - 2
    listed = api.invoke("bob", "list_my_orders", {})
    assert order["id"] in [o["id"] for o in listed["data"]["orders"]]
    # PENDING orders have neither payment nor shipment (table in section 1)
    assert api.get("payment", "/payments", params={"order_id": order["id"]}).status_code == 404
    assert api.shipment(order["id"]).status_code == 404


def test_uc74_pay_order_creates_payment_and_shipment(api):
    order = _placed_order(api)
    r = _invoke_as(api, "bob", "pay_order", {"order_id": order["id"], "method": "COD"},
                   f"thanh toán đơn {order['id']} bằng COD")
    assert r["_http"] == 422 and r["error"] == "invalid_arguments", r  # COD is not prepaid: not supported
    assert api.order(order["id"])["status"] == "PENDING"
    r = _invoke_as(api, "bob", "pay_order", {"order_id": order["id"], "method": "BANK_TRANSFER"},
                   f"thanh toán đơn {order['id']} bằng chuyển khoản")
    assert r["status"] == "ok" and r["data"]["order"]["status"] == "PAID", r
    pay = api.payment(order["id"])
    assert (pay["status"], pay["amount"], pay["method"], pay["user_id"]) == ("SUCCESS", 700_000, "BANK_TRANSFER", 2)
    ship = eventually(lambda: _eq(api.shipment(order["id"]).status_code, 200) and api.shipment(order["id"]).json())
    assert ship["status"] == "WAITING_PICKUP" and ship["address"] == BOB_DELIVERY["address"]
    assert api.invoke("bob", "get_shipment", {"order_id": order["id"]})["status"] == "ok"
    r = _invoke_as(api, "bob", "pay_order", {"order_id": order["id"], "method": "CARD"},
                   f"thanh toán đơn {order['id']}")
    assert r["error"] == "order_already_paid", r


def test_uc75_new_order_follows_refund_rules(api):
    before = api.stock(3)
    order = _placed_order(api)
    _invoke_as(api, "bob", "pay_order", {"order_id": order["id"], "method": "CARD"}, f"thanh toán đơn {order['id']}")
    eventually(lambda: _eq(api.shipment(order["id"]).status_code, 200))
    ticket = request_and_approve(api, "bob", full_refund(order["id"], 700_000))
    assert ticket["status"] == "EXECUTED", ticket
    eventually(lambda: _eq(api.order(order["id"])["status"], "REFUNDED"))
    assert api.shipment(order["id"]).json()["status"] == "CANCELLED"
    eventually(lambda: _eq(api.stock(3), before))


def test_uc76_cancel_placed_order_restocks(api):
    before = api.stock(3)
    order = _placed_order(api)
    assert api.stock(3) == before - 2
    r = api.invoke("bob", "cancel_order", {"order_id": order["id"]})
    assert r["data"]["status"] == "CANCELLED", r
    eventually(lambda: _eq(api.stock(3), before))
    r = _invoke_as(api, "bob", "pay_order", {"order_id": order["id"], "method": "CARD"}, f"thanh toán đơn {order['id']}")
    assert r["error"] == "order_not_payable", r


def test_uc77_ordering_rejections(api):
    r = api.invoke("bob", "quote_order", {"items": [{"product_id": 8, "qty": 1}], **BOB_DELIVERY})
    assert r["error"] == "out_of_stock", r
    r = api.invoke("bob", "quote_order", {"items": [{"product_id": 3, "qty": 1}], **BOB_DELIVERY,
                                          "recipient_phone": "abc"})
    assert r["error"] == "invalid_arguments", r
    code = _quote(api, "bob")["quote_id"]
    r = _place(api, "alice", code)  # another customer's quote
    assert r["error"] == "quote_not_found", r
    assert api.invoke("staff1", "quote_order", {"items": [{"product_id": 3, "qty": 1}], **BOB_DELIVERY})[
        "error"] == "tool_forbidden"
    tools = {t["function"]["name"] for t in api.get("gateway", "/tools", "staff1").json()}
    assert not tools & {"quote_order", "place_order", "pay_order"}


def test_uc78_pay_order_rules(api):
    r = _invoke_as(api, "bob", "pay_order", {"order_id": 1004, "method": "CARD"}, "thanh toán đơn này đi")
    assert r["_http"] == 403 and r["error"] == "confirmation_required", r
    r = _invoke_as(api, "alice", "pay_order", {"order_id": 1004, "method": "CARD"}, "thanh toán đơn 1004")
    assert r["error"] == "forbidden", r
    # seed order 1004 was not placed by chat: delivery info is asked for at payment time
    r = _invoke_as(api, "bob", "pay_order", {"order_id": 1004, "method": "CARD"}, "thanh toán đơn 1004")
    assert r["error"] == "delivery_info_required", r
    r = _invoke_as(api, "bob", "pay_order", {"order_id": 1004, "method": "CARD", **BOB_DELIVERY},
                   "thanh toán đơn 1004")
    assert r["status"] == "ok" and r["data"]["order"]["status"] == "PAID", r
    assert api.payment(1004)["amount"] == 450_000
    eventually(lambda: _eq(api.shipment(1004).json()["status"], "WAITING_PICKUP"))
