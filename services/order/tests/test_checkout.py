from datetime import timedelta

DELIVERY = {"recipient_name": "Trần Văn Bob", "recipient_phone": "0912345678", "address": "12 Lê Lợi, Quận 1, TP.HCM"}


def quote(client, headers, items=None, **kw):
    return client.post("/orders/quotes", headers=headers,
                       json={"items": items or [{"product_id": 3, "qty": 2}], **DELIVERY, **kw})


def place(client, headers, code):
    return client.post("/orders", headers=headers, json={"quote_id": code})


def test_quote_prices_items_without_touching_stock(client, bob, downstream):
    r = quote(client, bob, [{"product_id": 3, "qty": 1}, {"product_id": 4, "qty": 2}, {"product_id": 3, "qty": 1}])
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["quote_id"]) == 6 and body["order_id"] is None
    assert [(i["product_id"], i["qty"], i["subtotal"]) for i in body["items"]] == [(3, 2, 700_000), (4, 2, 300_000)]
    assert body["total"] == 1_000_000
    assert body["quote_id"] in body["next_step"]
    assert downstream.calls == []  # nothing reserved yet


def test_quote_rejects_unknown_or_out_of_stock(client, bob):
    r = quote(client, bob, [{"product_id": 99, "qty": 1}])
    assert r.status_code == 404 and r.json()["error"] == "product_not_found"
    r = quote(client, bob, [{"product_id": 8, "qty": 1}])
    assert r.status_code == 409 and r.json()["error"] == "out_of_stock"
    assert r.json()["items"][0]["available"] == 0
    assert quote(client, bob, recipient_phone="123").status_code == 422


def test_only_customers_order(client, staff):
    assert quote(client, staff).status_code == 403


def test_place_order_reserves_stock_once(client, bob, downstream):
    code = quote(client, bob).json()["quote_id"]
    r = place(client, bob, code.lower())  # code is case-insensitive
    assert r.status_code == 201, r.text
    order = r.json()["order"]
    assert order["status"] == "PENDING" and order["total"] == 700_000 and order["user_id"] == 2
    assert order["id"] > 1005
    assert r.json()["delivery"]["address"] == DELIVERY["address"]
    assert [c["body"]["items"] for c in downstream.calls] == [[{"product_id": 3, "qty": 2}]]
    again = place(client, bob, code)
    assert again.json()["order"]["id"] == order["id"]
    assert len(downstream.calls) == 1  # confirming twice reserves once
    assert [o["id"] for o in client.get("/orders", headers=bob).json()["orders"]][0] == order["id"]


def test_place_order_other_user_or_expired(client, alice, bob):
    from app.db import SessionLocal
    from app.models import Quote, utcnow_naive
    code = quote(client, bob).json()["quote_id"]
    r = place(client, alice, code)
    assert r.status_code == 404 and r.json()["error"] == "quote_not_found"
    with SessionLocal() as db:
        db.get(Quote, code).expires_at = utcnow_naive() - timedelta(minutes=1)
        db.commit()
    r = place(client, bob, code)
    assert r.status_code == 409 and r.json()["error"] == "quote_expired"


def test_place_order_out_of_stock_creates_nothing(client, bob, downstream):
    code = quote(client, bob).json()["quote_id"]
    downstream.products[3][2] = 1  # sold out meanwhile
    r = place(client, bob, code)
    assert r.status_code == 409 and r.json()["error"] == "out_of_stock"
    assert client.get("/orders", headers=bob).json()["total"] == 2


def test_pay_order_marks_paid_and_requests_shipment(client, bob, downstream):
    order_id = place(client, bob, quote(client, bob).json()["quote_id"]).json()["order"]["id"]
    r = client.post(f"/orders/{order_id}/pay", headers=bob, json={"method": "CARD"})
    assert r.status_code == 200, r.text
    assert r.json()["order"]["status"] == "PAID"
    assert r.json()["payment"] == {"amount": 700_000, "method": "CARD", "status": "SUCCESS"}
    shipment = [c for c in downstream.calls if c["url"] == "http://shipping/internal/shipments"]
    assert len(shipment) == 1 and shipment[0]["key"] == f"order-{order_id}-shipment"
    assert shipment[0]["body"]["address"] == DELIVERY["address"]
    r = client.post(f"/orders/{order_id}/pay", headers=bob, json={"method": "CARD"})
    assert r.status_code == 409 and r.json()["error"] == "order_already_paid"


def test_pay_order_rejects_cod(client, bob):
    r = client.post("/orders/1004/pay", headers=bob, json={"method": "COD", **DELIVERY})
    assert r.status_code == 422
    assert client.get("/orders/1004", headers=bob).json()["status"] == "PENDING"


def test_pay_order_rules(client, alice, bob, downstream):
    r = client.post("/orders/1004/pay", headers=alice, json={"method": "CARD"})
    assert r.status_code == 403
    # seed order 1004 has no delivery info yet
    r = client.post("/orders/1004/pay", headers=bob, json={"method": "CARD"})
    assert r.status_code == 422 and r.json()["error"] == "delivery_info_required"
    r = client.post("/orders/1004/pay", headers=bob, json={"method": "CARD", **DELIVERY})
    assert r.status_code == 200 and r.json()["order"]["status"] == "PAID"
    assert client.post("/orders/1004/cancel", headers=bob).json()["error"] == "order_already_paid"
    order_id = place(client, bob, quote(client, bob).json()["quote_id"]).json()["order"]["id"]
    client.post(f"/orders/{order_id}/cancel", headers=bob)
    r = client.post(f"/orders/{order_id}/pay", headers=bob, json={"method": "CARD"})
    assert r.status_code == 409 and r.json()["error"] == "order_not_payable"


def test_pay_order_payment_down_keeps_pending(client, bob, downstream):
    order_id = place(client, bob, quote(client, bob).json()["quote_id"]).json()["order"]["id"]
    downstream.fail = 1
    r = client.post(f"/orders/{order_id}/pay", headers=bob, json={"method": "CARD"})
    assert r.status_code == 503
    assert client.get(f"/orders/{order_id}", headers=bob).json()["status"] == "PENDING"


def test_checkout_tools_declared(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/orders/quotes"]["post"]["x-agent-tool"] == {"name": "quote_order", "risk": "low",
                                                               "roles": ["customer"]}
    assert paths["/orders"]["post"]["x-agent-tool"]["confirm_args"] == ["quote_id"]
    assert paths["/orders/{order_id}/pay"]["post"]["x-agent-tool"]["confirm_args"] == ["order_id"]
