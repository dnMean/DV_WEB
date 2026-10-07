def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_seed_has_eight_products_one_out_of_stock(client):
    stocks = [client.get(f"/inventory/{i}").json() for i in range(1, 9)]
    assert all("stock" in s for s in stocks)
    assert [s["product_id"] for s in stocks if s["stock"] == 0] == [8]


def test_search_no_auth_needed(client):
    r = client.get("/products/search", params={"q": "tai"})
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["Tai nghe Bluetooth Sony WH-CH520"]


def test_search_accent_insensitive_and_limit(client):
    names = [p["name"] for p in client.get("/products/search", params={"q": "sac"}).json()]
    assert "Sạc nhanh Anker 20W USB-C" in names
    assert "Sạc dự phòng Xiaomi 10000mAh" in names
    assert len(client.get("/products/search", params={"q": "sac", "limit": 1}).json()) == 1


def test_search_multi_word(client):
    r = client.get("/products/search", params={"q": "kính iphone"})
    assert [p["id"] for p in r.json()] == [6]


def test_search_like_wildcards_are_literal(client):
    assert client.get("/products/search", params={"q": "%"}).json() == []


def test_search_requires_q(client):
    r = client.get("/products/search")
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_get_product_and_404(client):
    assert client.get("/products/1").json()["price"] == 2_500_000
    r = client.get("/products/999")
    assert r.status_code == 404
    assert r.json()["error"] == "product_not_found"


def test_out_of_stock(client):
    body = client.get("/inventory/8").json()
    assert body == {"product_id": 8, "name": "Sạc dự phòng Xiaomi 10000mAh", "stock": 0, "in_stock": False}
    assert client.get("/products/8").json()["in_stock"] is False


def test_accepts_valid_jwt_rejects_bad_one(client, alice):
    assert client.get("/products/1", headers=alice).status_code == 200
    assert client.get("/products/1", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_openapi_tools(client):
    paths = client.get("/openapi.json").json()["paths"]
    names = {
        paths["/products/search"]["get"]["x-agent-tool"]["name"],
        paths["/products/{product_id}"]["get"]["x-agent-tool"]["name"],
        paths["/inventory/{product_id}"]["get"]["x-agent-tool"]["name"],
    }
    assert names == {"search_products", "get_product", "check_stock"}


INTERNAL = {"X-Internal-Secret": "test-internal"}


def test_restock_is_idempotent(client):
    body = {"items": [{"product_id": 4, "qty": 1}, {"product_id": 5, "qty": 2}], "reason": "cancel 1004"}
    before = [client.get(f"/inventory/{p}").json()["stock"] for p in (4, 5)]
    r = client.post("/internal/inventory/restock", json=body, headers={**INTERNAL, "Idempotency-Key": "k1"})
    assert r.json() == {"replayed": False}
    r = client.post("/internal/inventory/restock", json=body, headers={**INTERNAL, "Idempotency-Key": "k1"})
    assert r.json() == {"replayed": True}
    after = [client.get(f"/inventory/{p}").json()["stock"] for p in (4, 5)]
    assert after == [before[0] + 1, before[1] + 2]


def test_restock_requires_internal_secret_and_key(client):
    body = {"items": [{"product_id": 4, "qty": 1}]}
    assert client.post("/internal/inventory/restock", json=body, headers={"Idempotency-Key": "k"}).status_code == 403
    assert client.post("/internal/inventory/restock", json=body, headers=INTERNAL).status_code == 400
    r = client.post("/internal/inventory/restock", json={"items": [{"product_id": 99, "qty": 1}]},
                    headers={**INTERNAL, "Idempotency-Key": "k2"})
    assert r.status_code == 422


def test_reset_restores_seed(client):
    client.post("/internal/inventory/restock", json={"items": [{"product_id": 8, "qty": 5}]},
                headers={**INTERNAL, "Idempotency-Key": "k3"})
    assert client.get("/inventory/8").json()["stock"] == 5
    assert client.post("/internal/reset", headers=INTERNAL).status_code == 200
    assert client.get("/inventory/8").json()["stock"] == 0


def test_catalog_returns_price_and_stock(client):
    r = client.get("/internal/products", params={"ids": "3,8,99"}, headers=INTERNAL)
    assert r.json() == [
        {"id": 3, "name": "Sạc nhanh Anker 20W USB-C", "price": 350_000, "stock": 45},
        {"id": 8, "name": "Sạc dự phòng Xiaomi 10000mAh", "price": 400_000, "stock": 0},
    ]
    assert client.get("/internal/products", params={"ids": "3"}).status_code == 403


def test_reserve_decrements_once(client):
    body = {"items": [{"product_id": 4, "qty": 2}, {"product_id": 5, "qty": 1}], "reason": "order 1006"}
    headers = {**INTERNAL, "Idempotency-Key": "order-1006-reserve"}
    r = client.post("/internal/inventory/reserve", json=body, headers=headers)
    assert r.status_code == 200 and r.json()["replayed"] is False
    assert {i["id"]: i["price"] for i in r.json()["items"]} == {4: 150_000, 5: 200_000}
    assert client.post("/internal/inventory/reserve", json=body, headers=headers).json()["replayed"] is True
    assert [client.get(f"/inventory/{p}").json()["stock"] for p in (4, 5)] == [78, 34]


def test_reserve_is_all_or_nothing(client):
    body = {"items": [{"product_id": 4, "qty": 1}, {"product_id": 8, "qty": 1}]}
    r = client.post("/internal/inventory/reserve", json=body, headers={**INTERNAL, "Idempotency-Key": "k"})
    assert r.status_code == 409
    assert r.json()["error"] == "out_of_stock"
    assert r.json()["items"] == [{"product_id": 8, "name": "Sạc dự phòng Xiaomi 10000mAh", "requested": 1,
                                  "available": 0}]
    assert client.get("/inventory/4").json()["stock"] == 80  # nothing reserved
    r = client.post("/internal/inventory/reserve", json={"items": [{"product_id": 99, "qty": 1}]},
                    headers={**INTERNAL, "Idempotency-Key": "k2"})
    assert r.status_code == 422
