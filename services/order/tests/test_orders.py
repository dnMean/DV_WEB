from opspilot_common.auth import create_system_token


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_token(client):
    r = client.get("/orders")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_invalid_token(client):
    r = client.get("/orders", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_customer_lists_only_own_orders(client, alice):
    r = client.get("/orders", headers=alice)
    assert r.status_code == 200
    assert sorted(o["id"] for o in r.json()["orders"]) == [1001, 1002, 1003]


def test_customer_cannot_list_other_user(client, alice):
    r = client.get("/orders", params={"user_id": 2}, headers=alice)
    assert r.status_code == 403


def test_staff_lists_by_user(client, staff):
    r = client.get("/orders", params={"user_id": 2}, headers=staff)
    assert sorted(o["id"] for o in r.json()["orders"]) == [1004, 1005]


def test_filter_by_status(client, alice):
    r = client.get("/orders", params={"status": "PAID"}, headers=alice)
    assert [o["id"] for o in r.json()["orders"]] == [1003]


def test_get_order_shape(client, alice):
    r = client.get("/orders/1002", headers=alice)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "SHIPPING"
    assert body["total"] == 1_200_000
    assert body["items"][0] == {
        "product_id": 2, "name": "Tai nghe Bluetooth Sony WH-CH520", "qty": 1, "price": 1_200_000,
    }
    assert set(body) == {"id", "user_id", "status", "total", "refunded_amount", "items", "note", "created_at"}


def test_get_order_forbidden_and_not_found(client, alice):
    r = client.get("/orders/1004", headers=alice)
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
    r = client.get("/orders/9999", headers=alice)
    assert r.status_code == 404
    assert r.json()["error"] == "order_not_found"


def test_seed_totals_match_items(client, staff):
    for row in client.get("/orders", headers=staff).json()["orders"]:
        order = client.get(f"/orders/{row['id']}", headers=staff).json()
        assert order["total"] == sum(i["qty"] * i["price"] for i in order["items"])


def test_list_is_compact_and_paginated(client, alice):
    rows = client.get("/orders", headers=alice).json()["orders"]
    assert rows[0]["items"] == "Điện thoại Samsung Galaxy A15 x1" and "note" not in rows[0]
    assert [o["id"] for o in client.get("/orders", params={"limit": 1, "offset": 1}, headers=alice).json()["orders"]] == [1002]


def test_reset_with_generated_orders(client, staff, alice):
    assert client.post("/internal/reset", params={"extra_orders": 100}, headers=INTERNAL).json()["extra_orders"] == 100
    rows = client.get("/orders/search", params={"limit": 200}, headers=staff).json()["orders"]
    assert len(rows) == 105 and {o["user_id"] for o in rows} == {1, 2}
    assert {o["status"] for o in rows} >= {"PENDING", "PAID", "SHIPPING", "DELIVERED", "CANCELLED", "REFUNDED"}
    for row in rows[:20]:
        order = client.get(f"/orders/{row['id']}", headers=staff).json()
        assert order["total"] == sum(i["qty"] * i["price"] for i in order["items"])
        assert 0 <= order["refunded_amount"] <= order["total"]
    assert client.post("/internal/reset", params={"extra_orders": 0}, headers=INTERNAL).status_code == 200
    assert client.get("/orders/search", headers=staff).json()["total"] == 5


def test_injection_note_seeded(client, bob):
    assert "IGNORE PREVIOUS INSTRUCTIONS" in client.get("/orders/1005", headers=bob).json()["note"]


def test_cancel_pending_is_idempotent(client, bob):
    r = client.post("/orders/1004/cancel", headers=bob)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"
    r = client.post("/orders/1004/cancel", headers=bob)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"


def test_cancel_paid_suggests_refund(client, alice):
    r = client.post("/orders/1003/cancel", headers=alice)
    assert r.status_code == 409
    assert r.json()["error"] == "order_already_paid"
    assert r.json()["suggested_tool"] == "refund_payment"


def test_cancel_shipping_conflict(client, alice):
    r = client.post("/orders/1002/cancel", headers=alice)
    assert r.status_code == 409
    assert r.json()["error"] == "order_not_cancellable"


def test_cancel_other_users_order_forbidden(client, alice):
    assert client.post("/orders/1004/cancel", headers=alice).status_code == 403


def test_system_token_rejected_for_order_endpoints(client):
    headers = {"Authorization": f"Bearer {create_system_token()}", "X-On-Behalf-Of": "1"}
    assert client.get("/orders", headers=headers).status_code == 403


def test_request_id_echoed(client, alice):
    r = client.get("/orders/1001", headers={**alice, "X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert client.get("/health").headers["X-Request-ID"]


def test_openapi_declares_agent_tools(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/orders"]["get"]["x-agent-tool"] == {"name": "list_my_orders", "risk": "low", "roles": ["customer"]}
    assert paths["/orders/search"]["get"]["x-agent-tool"]["roles"] == ["staff"]
    assert paths["/orders/{order_id}"]["get"]["x-agent-tool"] == {
        "name": "get_order", "risk": "low", "roles": ["customer", "staff"],
    }
    assert paths["/orders/{order_id}/cancel"]["post"]["x-agent-tool"]["risk"] == "medium"
    assert "x-agent-tool" not in paths["/health"]["get"]


INTERNAL = {"X-Internal-Secret": "test-internal"}


def test_cancel_queues_restock_once(client, bob, downstream):
    client.post("/orders/1004/cancel", headers=bob)
    client.post("/orders/1004/cancel", headers=bob)
    assert len(downstream.calls) == 1
    call = downstream.calls[0]
    assert call["url"] == "http://product/internal/inventory/restock"
    assert call["key"] == "order-1004-restock" and call["secret"] == "test-internal"
    assert sorted((i["product_id"], i["qty"]) for i in call["body"]["items"]) == [(4, 1), (5, 1), (6, 1)]


def test_outbox_retries_when_product_down(client, bob, downstream):
    from app.outbox import outbox
    from app.db import SessionLocal
    from app.models import OutboxMessage
    downstream.fail = 1
    client.post("/orders/1004/cancel", headers=bob)
    assert downstream.calls == []  # first attempt failed, kept for retry
    with SessionLocal() as db:
        row = db.query(OutboxMessage).one()
        assert row.status == "PENDING" and row.attempts == 1
        row.next_attempt_at = row.created_at  # due now
        db.commit()
    outbox.flush()
    assert len(downstream.calls) == 1
    with SessionLocal() as db:
        assert db.query(OutboxMessage).one().status == "DONE"


def test_internal_requires_secret(client):
    assert client.get("/internal/orders/1003").status_code == 403
    assert client.get("/internal/orders/1003", headers=INTERNAL).json()["status"] == "PAID"


def test_full_refund_of_paid_order_refunds_and_restocks(client, alice, downstream):
    r = client.post("/internal/orders/1003/refund-applied", headers=INTERNAL,
                    json={"total_refunded": 2_500_000, "full": True})
    assert r.json()["status"] == "REFUNDED" and r.json()["refunded_amount"] == 2_500_000
    assert downstream.calls[0]["body"]["items"] == [{"product_id": 1, "qty": 1}]
    # replay is harmless
    client.post("/internal/orders/1003/refund-applied", headers=INTERNAL, json={"total_refunded": 2_500_000, "full": True})
    assert len(downstream.calls) == 1
    assert client.get("/orders/1003", headers=alice).json()["status"] == "REFUNDED"


def test_partial_refund_after_delivery_keeps_status(client, downstream):
    r = client.post("/internal/orders/1001/refund-applied", headers=INTERNAL,
                    json={"total_refunded": 100_000, "full": False})
    assert r.json()["status"] == "DELIVERED" and r.json()["refunded_amount"] == 100_000
    r = client.post("/internal/orders/1001/refund-applied", headers=INTERNAL,
                    json={"total_refunded": 350_000, "full": True})
    assert r.json()["status"] == "REFUNDED"
    assert downstream.calls == []  # delivered goods are not restocked


def test_refund_applied_invalid_states(client):
    for order_id, full in ((1004, True), (1002, True), (1003, False)):
        r = client.post(f"/internal/orders/{order_id}/refund-applied", headers=INTERNAL,
                        json={"total_refunded": 1, "full": full})
        assert r.status_code == 409, order_id


def test_shipping_status_transitions(client):
    def send(order_id, status):
        return client.post(f"/internal/orders/{order_id}/shipping-status", headers=INTERNAL, json={"status": status})
    assert send(1003, "IN_TRANSIT").json()["status"] == "SHIPPING"
    assert send(1003, "IN_TRANSIT").json()["status"] == "SHIPPING"  # idempotent
    assert send(1003, "DELIVERED").json()["status"] == "DELIVERED"
    assert send(1001, "IN_TRANSIT").status_code == 409  # backwards
    assert send(1004, "IN_TRANSIT").status_code == 409  # unpaid


def test_reset(client, bob):
    client.post("/orders/1004/cancel", headers=bob)
    assert client.post("/internal/reset", headers=INTERNAL).status_code == 200
    assert client.get("/orders/1004", headers=bob).json()["status"] == "PENDING"


def test_search_orders_staff_only_with_filters(client, alice, staff):
    def ids(**params):
        return sorted(o["id"] for o in client.get("/orders/search", params=params, headers=staff).json()["orders"])
    assert client.get("/orders/search", headers=alice).status_code == 403
    assert ids() == [1001, 1002, 1003, 1004, 1005]
    assert ids(user_id=2) == [1004, 1005]
    assert ids(order_id=1002) == [1002]
    assert ids(status="PAID") == [1003, 1005]
    assert ids(refunded="true") == []
    client.post("/internal/orders/1001/refund-applied", headers=INTERNAL, json={"total_refunded": 1, "full": False})
    assert ids(refunded="true") == [1001]
    assert ids(refunded="false", user_id=1) == [1002, 1003]


def test_page_reports_total_beyond_limit(client, alice):
    page = client.get("/orders", params={"limit": 2}, headers=alice).json()
    assert (page["total"], page["has_more"], len(page["orders"])) == (3, True, 2)
    page = client.get("/orders", params={"limit": 2, "offset": 2}, headers=alice).json()
    assert (page["has_more"], [o["id"] for o in page["orders"]]) == (False, [1001])
    assert client.get("/orders", params={"status": "SHIPPING"}, headers=alice).json()["total"] == 1
