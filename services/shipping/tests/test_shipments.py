NEW_ADDRESS = {"address": "12 Lê Lợi, Quận 1, TP.HCM"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_seed(client, alice):
    s1002 = client.get("/shipments/1002", headers=alice).json()
    assert s1002["status"] == "IN_TRANSIT"
    assert len(s1002["events"]) == 3
    assert client.get("/shipments/1001", headers=alice).json()["status"] == "DELIVERED"
    assert client.get("/shipments/1003", headers=alice).json()["status"] == "WAITING_PICKUP"


def test_ownership_and_404(client, bob, staff):
    assert client.get("/shipments/1002", headers=bob).status_code == 403
    assert client.get("/shipments/1002", headers=staff).status_code == 200
    r = client.get("/shipments/1004", headers=bob)
    assert r.status_code == 404
    assert r.json()["error"] == "shipment_not_found"


def test_update_address_waiting_pickup(client, alice):
    r = client.put("/shipments/1003/address", json=NEW_ADDRESS, headers=alice)
    assert r.status_code == 200
    assert r.json()["address"] == NEW_ADDRESS["address"]
    assert len(r.json()["events"]) == 2
    # same request again: no new event
    r = client.put("/shipments/1003/address", json=NEW_ADDRESS, headers=alice)
    assert len(r.json()["events"]) == 2


def test_update_address_conflict_when_in_transit(client, alice):
    r = client.put("/shipments/1002/address", json=NEW_ADDRESS, headers=alice)
    assert r.status_code == 409
    assert r.json()["error"] == "shipment_not_editable"


def test_update_address_forbidden_and_validation(client, bob, alice):
    assert client.put("/shipments/1003/address", json=NEW_ADDRESS, headers=bob).status_code == 403
    r = client.put("/shipments/1003/address", json={"address": "x"}, headers=alice)
    assert r.status_code == 422
    r = client.put("/shipments/1003/address", json={**NEW_ADDRESS, "recipient_phone": "123"}, headers=alice)
    assert r.status_code == 422


def test_openapi_tools(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/shipments/{order_id}"]["get"]["x-agent-tool"]["name"] == "get_shipment"
    assert paths["/shipments/{order_id}/address"]["put"]["x-agent-tool"]["risk"] == "medium"


INTERNAL = {"X-Internal-Secret": "test-internal"}


def _advance(client, headers, order_id, status):
    return client.post(f"/shipments/{order_id}/advance", headers=headers,
                       json={"status": status, "location": "Kho", "description": status})


def test_seed_1005_has_shipment(client, bob):
    s = client.get("/shipments/1005", headers=bob).json()
    assert s["status"] == "WAITING_PICKUP" and s["recipient_phone"] == "0912345678"


def test_advance_syncs_order(client, staff, downstream):
    assert _advance(client, staff, 1003, "IN_TRANSIT").json()["status"] == "IN_TRANSIT"
    assert _advance(client, staff, 1003, "IN_TRANSIT").status_code == 200  # extra event, no new sync
    assert _advance(client, staff, 1003, "DELIVERED").json()["status"] == "DELIVERED"
    assert [(c["url"], c["body"]["status"], c["key"]) for c in downstream.calls] == [
        ("http://order/internal/orders/1003/shipping-status", "IN_TRANSIT", "shipment-1003-IN_TRANSIT"),
        ("http://order/internal/orders/1003/shipping-status", "DELIVERED", "shipment-1003-DELIVERED"),
    ]


def test_advance_invalid(client, staff, alice):
    assert _advance(client, staff, 1001, "IN_TRANSIT").status_code == 409  # delivered: no going back
    assert _advance(client, staff, 1003, "DELIVERED").status_code == 409  # must be picked up first
    assert _advance(client, alice, 1003, "IN_TRANSIT").status_code == 403


def test_internal_cancel(client, staff):
    assert client.post("/internal/shipments/1003/cancel").status_code == 403
    r = client.post("/internal/shipments/1003/cancel", headers=INTERNAL)
    assert r.json()["status"] == "CANCELLED"
    assert client.post("/internal/shipments/1003/cancel", headers=INTERNAL).status_code == 200  # idempotent
    assert _advance(client, staff, 1003, "IN_TRANSIT").status_code == 409
    r = client.post("/internal/shipments/1002/cancel", headers=INTERNAL)
    assert r.status_code == 409 and r.json()["error"] == "shipment_already_dispatched"


def test_address_locked_after_cancel(client, alice):
    client.post("/internal/shipments/1003/cancel", headers=INTERNAL)
    r = client.put("/shipments/1003/address", json=NEW_ADDRESS, headers=alice)
    assert r.status_code == 409


def test_staff_lists_shipments(client, staff, alice):
    assert client.get("/shipments", headers=alice).status_code == 403
    assert sorted(s["order_id"] for s in client.get("/shipments", headers=staff).json()) == [1001, 1002, 1003, 1005]
    only = client.get("/shipments", params={"status": "IN_TRANSIT"}, headers=staff).json()
    assert [s["order_id"] for s in only] == [1002]


def test_reset_with_generated_orders(client, staff):
    client.post("/internal/reset", params={"extra_orders": 100}, headers=INTERNAL)
    rows = client.get("/shipments", headers=staff).json()
    assert len(rows) > 50
    for s in [r for r in rows if r["order_id"] >= 1006]:  # generated demo shipments
        assert s["events"][0]["status"] == "WAITING_PICKUP"
        assert s["events"][-1]["status"] == s["status"] or s["status"] == "IN_TRANSIT"


def test_advance_is_staff_agent_tool_with_defaults(client, staff):
    op = client.get("/openapi.json").json()["paths"]["/shipments/{order_id}/advance"]["post"]
    assert op["x-agent-tool"] == {"name": "update_shipment_status", "risk": "medium", "roles": ["staff"],
                                  "confirm_args": ["order_id"]}
    r = client.post("/shipments/1003/advance", headers=staff, json={"status": "IN_TRANSIT"}).json()
    assert (r["events"][-1]["location"], r["events"][-1]["description"]) == ("Kho TP.HCM", "Đã lấy hàng, đang vận chuyển")


def test_internal_create_shipment_is_idempotent(client, bob):
    body = {"order_id": 1006, "user_id": 2, "recipient_name": "Trần Văn Bob", "recipient_phone": "0912345678",
            "address": "12 Lê Lợi, Quận 1, TP.HCM"}
    assert client.post("/internal/shipments", json=body).status_code == 403
    r = client.post("/internal/shipments", json=body, headers=INTERNAL)
    assert r.status_code == 200
    assert r.json()["status"] == "WAITING_PICKUP" and r.json()["tracking_code"] == "GHN1006VN"
    assert len(r.json()["events"]) == 1
    again = client.post("/internal/shipments", json={**body, "address": "khác"}, headers=INTERNAL).json()
    assert again["address"] == body["address"] and len(again["events"]) == 1
    assert client.get("/shipments/1006", headers=bob).json()["recipient_name"] == "Trần Văn Bob"
