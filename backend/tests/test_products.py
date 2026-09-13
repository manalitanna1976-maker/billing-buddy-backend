def _headers(client, email="owner@prod.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_and_list_products(client):
    headers = _headers(client)

    client.post("/products", headers=headers, json={"name": "Steel Rod 12mm", "hsn_sac": "7213"})
    client.post("/products", headers=headers, json={"name": "Steel Rod 16mm", "hsn_sac": "7213"})

    resp = client.get("/products", headers=headers, params={"q": "12mm"})
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert names == ["Steel Rod 12mm"]


def test_create_product_defaults_manual_flags_false(client):
    headers = _headers(client)
    resp = client.post("/products", headers=headers, json={"name": "Steel Rod 12mm"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["auto_created"] is False
    assert body["needs_review"] is False
    assert body["current_qty"] == "0.000"


def test_create_product_duplicate_name_conflicts(client):
    headers = _headers(client)
    client.post("/products", headers=headers, json={"name": "Acme Pvt Ltd Rod"})
    resp = client.post("/products", headers=headers, json={"name": "Acme Pvt. Ltd. Rod"})
    assert resp.status_code == 409


def test_update_product_cannot_set_current_qty(client):
    headers = _headers(client)
    create_resp = client.post("/products", headers=headers, json={"name": "Steel Rod"})
    product_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/products/{product_id}",
        headers=headers,
        json={"reorder_level": "5", "current_qty": "999"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["current_qty"] == "0.000"
    assert update_resp.json()["reorder_level"] == "5.000"


def test_adjust_stock_updates_qty_and_creates_movement(client):
    headers = _headers(client)
    create_resp = client.post("/products", headers=headers, json={"name": "Steel Rod"})
    product_id = create_resp.json()["id"]

    resp = client.post(
        f"/products/{product_id}/adjust-stock",
        headers=headers,
        json={"delta_qty": "10", "note": "opening stock"},
    )
    assert resp.status_code == 200
    assert resp.json()["current_qty"] == "10.000"

    movements = client.get(f"/products/{product_id}/stock-movements", headers=headers)
    assert movements.status_code == 200
    assert len(movements.json()) == 1
    assert movements.json()[0]["reason"] == "manual_adjustment"
    assert movements.json()[0]["note"] == "opening stock"


def test_adjust_stock_rejects_zero_delta(client):
    headers = _headers(client)
    create_resp = client.post("/products", headers=headers, json={"name": "Steel Rod"})
    product_id = create_resp.json()["id"]

    resp = client.post(
        f"/products/{product_id}/adjust-stock", headers=headers, json={"delta_qty": "0"}
    )
    assert resp.status_code == 422


def test_products_are_scoped_to_business(client):
    headers_a = _headers(client, "a@prod.test")
    headers_b = _headers(client, "b@prod.test")
    create_resp = client.post("/products", headers=headers_a, json={"name": "Steel Rod"})
    product_id = create_resp.json()["id"]

    resp = client.get(f"/products/{product_id}", headers=headers_b)
    assert resp.status_code == 404
