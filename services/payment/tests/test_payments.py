"""Refund rules from docs/USECASES.md section 2."""
import pytest

from opspilot_common.auth import create_system_token


def _system(on_behalf_of: int, key: str) -> dict:
    return {"Authorization": f"Bearer {create_system_token()}", "X-On-Behalf-Of": str(on_behalf_of),
            "Idempotency-Key": key}


def body(order_id=1003, amount=2_500_000, reason="Giao nhầm màu"):
    return {"order_id": order_id, "amount": amount, "reason": reason}


def refund(client, headers, key="k", **kw):
    return client.post("/refunds", json=body(**kw), headers={**headers, "Idempotency-Key": key})


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# --- lookups ---------------------------------------------------------------------------------

def test_get_payment_owner(client, alice):
    body_ = client.get("/payments", params={"order_id": 1003}, headers=alice).json()
    assert (body_["amount"], body_["status"], body_["refundable_amount"]) == (2_500_000, "SUCCESS", 2_500_000)


def test_get_payment_forbidden_and_missing(client, alice, staff):
    assert client.get("/payments", params={"order_id": 1005}, headers=alice).status_code == 403
    assert client.get("/payments", params={"order_id": 1004}, headers=alice).json()["error"] == "payment_not_found"
    assert client.get("/payments", params={"order_id": 1005}, headers=staff).status_code == 200


# --- validate (precheck) ---------------------------------------------------------------------

@pytest.mark.parametrize("who,kw,error", [
    ("alice", dict(order_id=1003, amount=500_000), "full_refund_required"),   # UC21
    ("alice", dict(order_id=1002, amount=100_000), "order_in_transit"),       # UC22
    ("alice", dict(order_id=1001, amount=9_999_999), "amount_exceeds_refundable"),  # UC27
    ("bob", dict(order_id=1004, amount=450_000), "order_not_paid"),           # UC28
    ("alice", dict(order_id=1005, amount=800_000), "forbidden"),              # UC29
    ("alice", dict(order_id=9999, amount=1), "order_not_found"),
])
def test_validate_rejections(client, request, who, kw, error):
    r = client.post("/refunds/validate", json=body(**kw), headers=request.getfixturevalue(who))
    assert r.json()["error"] == error, r.json()


def test_validate_ok(client, alice):
    r = client.post("/refunds/validate", json=body(1003, 2_500_000), headers=alice).json()
    assert r == {"eligible": True, "order_status": "PAID", "refundable_amount": 2_500_000, "full_refund_required": True}
    r = client.post("/refunds/validate", json=body(1001, 100_000), headers=alice).json()
    assert r["eligible"] and r["full_refund_required"] is False


def test_validate_shipment_already_left(client, alice, world):
    world.shipments[1003] = "IN_TRANSIT"  # order not synced yet, shipment is the source of truth
    r = client.post("/refunds/validate", json=body(1003, 2_500_000), headers=alice)
    assert r.json()["error"] == "order_in_transit"


def test_validate_dependency_down(client, alice, world):
    world.shipping_down = True
    r = client.post("/refunds/validate", json=body(1003, 2_500_000), headers=alice)
    assert r.status_code == 503 and r.json()["error"] == "dependency_unavailable"


# --- execute -----------------------------------------------------------------------------------

def test_customer_cannot_refund_directly(client, alice):  # UC32
    assert refund(client, alice).status_code == 403


def test_refund_requires_idempotency_key(client, staff):
    assert client.post("/refunds", json=body(), headers=staff).json()["error"] == "idempotency_key_required"


def test_full_refund_before_shipping_cancels_shipment_and_notifies_order(client, alice, world):  # UC20
    r = client.post("/refunds", json=body(), headers=_system(1, "ticket-1"))
    assert r.status_code == 200 and r.json()["replayed"] is False
    assert world.shipments[1003] == "CANCELLED"
    assert world.refund_applied == [(1003, {"total_refunded": 2_500_000, "full": True})]
    assert client.get("/payments", params={"order_id": 1003}, headers=alice).json()["status"] == "REFUNDED"


def test_replay_same_key(client, world):  # UC33
    r1 = client.post("/refunds", json=body(), headers=_system(1, "ticket-1"))
    r2 = client.post("/refunds", json=body(), headers=_system(1, "ticket-1"))
    assert r2.json()["replayed"] is True and r2.json()["refund"]["id"] == r1.json()["refund"]["id"]
    assert len(world.refund_applied) == 1


def test_same_key_different_body_conflicts(client):
    client.post("/refunds", json=body(1001, 100_000), headers=_system(1, "k"))
    assert client.post("/refunds", json=body(1001, 1), headers=_system(1, "k")).status_code == 409


def test_shipment_left_between_ticket_and_execution(client, alice, world):  # UC31
    world.shipments[1003] = "IN_TRANSIT"
    r = client.post("/refunds", json=body(), headers=_system(1, "t"))
    assert r.status_code == 409 and r.json()["error"] == "order_in_transit"
    assert client.get("/payments", params={"order_id": 1003}, headers=alice).json()["refunds"] == []
    assert world.refund_applied == []


def test_shipping_down_means_no_refund(client, alice, world):
    world.shipping_down = True
    r = client.post("/refunds", json=body(), headers=_system(1, "t"))
    assert r.status_code == 503
    assert client.get("/payments", params={"order_id": 1003}, headers=alice).json()["refunds"] == []


def test_partial_then_full_after_delivery(client, alice, world):  # UC23, UC24
    assert refund(client, _system(1, "a"), key="a", order_id=1001, amount=100_000).status_code == 200
    p = client.get("/payments", params={"order_id": 1001}, headers=alice).json()
    assert (p["status"], p["refundable_amount"]) == ("PARTIALLY_REFUNDED", 250_000)
    assert world.shipments[1001] == "DELIVERED"  # delivered goods: shipment untouched
    r = refund(client, _system(1, "b"), key="b", order_id=1001, amount=300_000)
    assert r.json()["error"] == "amount_exceeds_refundable" and r.json()["refundable_amount"] == 250_000
    assert refund(client, _system(1, "c"), key="c", order_id=1001, amount=250_000).status_code == 200
    assert world.refund_applied == [(1001, {"total_refunded": 100_000, "full": False}),
                                    (1001, {"total_refunded": 350_000, "full": True})]
    world.orders[1001][1] = "REFUNDED"
    assert refund(client, _system(1, "d"), key="d", order_id=1001, amount=1).json()["error"] == "order_not_refundable"


def test_execution_rechecks_order_state(client, world):
    world.orders[1003][1] = "REFUNDED"
    assert client.post("/refunds", json=body(), headers=_system(1, "x")).json()["error"] == "order_not_refundable"


def test_system_token_ownership(client):
    assert client.post("/refunds", json=body(), headers=_system(2, "x")).status_code == 403
    headers = _system(1, "y")
    del headers["X-On-Behalf-Of"]
    assert client.post("/refunds", json=body(), headers=headers).status_code == 400


@pytest.mark.parametrize("amount", [0, -5])
def test_amount_must_be_positive(client, staff, amount):
    assert refund(client, staff, amount=amount).status_code == 422


def test_order_sync_retried_when_order_down(client, world):
    from app.db import SessionLocal
    from app.models import OutboxMessage
    from app.outbox import outbox

    world.order_sync_down = True
    assert client.post("/refunds", json=body(), headers=_system(1, "t")).status_code == 200  # money moved
    assert world.refund_applied == []
    with SessionLocal() as db:
        row = db.query(OutboxMessage).one()
        assert (row.status, row.attempts) == ("PENDING", 1)
        row.next_attempt_at = row.created_at  # make it due now
        db.commit()
    world.order_sync_down = False
    outbox.flush()
    assert world.refund_applied == [(1003, {"total_refunded": 2_500_000, "full": True})]


@pytest.mark.parametrize("who,order_id,expected", [
    ("alice", 1002, (False, "order_in_transit", 0, False)),
    ("alice", 1003, (True, "ok", 2_500_000, True)),
    ("alice", 1001, (True, "ok", 350_000, False)),
    ("bob", 1004, (False, "order_not_paid", 0, False)),
])
def test_eligibility(client, request, who, order_id, expected):
    r = client.get("/refunds/eligibility", params={"order_id": order_id}, headers=request.getfixturevalue(who)).json()
    assert (r["eligible"], r["reason"], r["max_refundable"], r["full_refund_required"]) == expected
    assert r["message"]


def test_eligibility_other_users_order_forbidden(client, alice):
    assert client.get("/refunds/eligibility", params={"order_id": 1005}, headers=alice).status_code == 403


def test_eligibility_after_refund(client, alice, world):
    client.post("/refunds", json=body(), headers=_system(1, "t"))
    world.orders[1003][1] = "REFUNDED"
    r = client.get("/refunds/eligibility", params={"order_id": 1003}, headers=alice).json()
    assert (r["eligible"], r["reason"]) == (False, "order_not_refundable")


def test_openapi_tools(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/payments"]["get"]["x-agent-tool"]["name"] == "get_payment"
    assert paths["/refunds"]["post"]["x-agent-tool"] == {
        "name": "refund_payment", "risk": "high", "roles": ["customer"],
        "dedup_fields": ["order_id"], "precheck": "/refunds/validate",
    }
    assert "x-agent-tool" not in paths["/refunds/validate"]["post"]
    assert paths["/refunds/eligibility"]["get"]["x-agent-tool"]["name"] == "check_refund_eligibility"


def test_internal_charge_is_idempotent(client, bob):
    body = {"order_id": 1006, "user_id": 2, "amount": 300_000, "method": "COD"}
    internal = {"X-Internal-Secret": "test-internal"}
    assert client.post("/internal/payments", json=body).status_code == 403
    first = client.post("/internal/payments", json=body, headers=internal)
    assert first.status_code == 200 and first.json()["status"] == "SUCCESS"
    again = client.post("/internal/payments", json=body, headers=internal)
    assert again.json()["id"] == first.json()["id"]
    r = client.post("/internal/payments", json={**body, "amount": 1}, headers=internal)
    assert r.status_code == 409 and r.json()["error"] == "payment_conflict"
    r = client.get("/payments", params={"order_id": 1006}, headers=bob)
    assert r.json()["amount"] == 300_000 and r.json()["refundable_amount"] == 300_000
