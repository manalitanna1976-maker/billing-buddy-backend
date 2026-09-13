from decimal import Decimal


def _setup(client, email="owner@purch.test"):
    signup = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    supplier = client.post("/suppliers", headers=headers, json={"name": "Acme Steel Co"})
    return headers, supplier.json()["id"]


def test_create_purchase_computes_totals_creates_product_and_stock(client):
    headers, supplier_id = _setup(client)

    resp = client.post(
        "/purchases",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "invoice_no": "INV-1",
            "invoice_date": "2026-08-16",
            "line_items": [
                {
                    "product_name": "Steel Rod 12mm",
                    "qty": "10",
                    "price": "100",
                    "gst_rate": "18",
                }
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert Decimal(str(body["taxable_total"])) == Decimal("1000.00")
    assert Decimal(str(body["tax_total"])) == Decimal("180.00")
    assert Decimal(str(body["grand_total"])) == Decimal("1180.00")
    assert body["origin"] == "manual"
    assert len(body["line_items"]) == 1

    products = client.get("/products", headers=headers, params={"q": "Steel Rod"}).json()
    assert len(products) == 1
    assert products[0]["current_qty"] == "10.000"
    assert products[0]["auto_created"] is False

    movements = client.get(
        f"/products/{products[0]['id']}/stock-movements", headers=headers
    ).json()
    assert len(movements) == 1
    assert movements[0]["reason"] == "purchase"
    assert movements[0]["ref_type"] == "purchase"


def test_create_purchase_with_existing_product_reuses_it(client):
    headers, supplier_id = _setup(client)
    product = client.post("/products", headers=headers, json={"name": "Steel Rod"}).json()

    resp = client.post(
        "/purchases",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "line_items": [
                {"product_id": product["id"], "qty": "5", "price": "50", "gst_rate": "0"}
            ],
        },
    )
    assert resp.status_code == 201

    refreshed = client.get(f"/products/{product['id']}", headers=headers).json()
    assert refreshed["current_qty"] == "5.000"


def test_create_purchase_includes_shipping_other_and_round_off(client):
    headers, supplier_id = _setup(client)

    resp = client.post(
        "/purchases",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "shipping_total": "20",
            "other_charges": "5",
            "round_off": "-0.50",
            "line_items": [
                {"product_name": "Widget", "qty": "1", "price": "100", "gst_rate": "0"}
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert Decimal(str(body["grand_total"])) == Decimal("124.50")


def test_create_purchase_duplicate_invoice_no_for_supplier_conflicts(client):
    headers, supplier_id = _setup(client)
    payload = {
        "supplier_id": supplier_id,
        "invoice_no": "DUP-1",
        "line_items": [{"product_name": "Widget", "qty": "1", "price": "10", "gst_rate": "0"}],
    }
    first = client.post("/purchases", headers=headers, json=payload)
    assert first.status_code == 201

    second = client.post("/purchases", headers=headers, json=payload)
    assert second.status_code == 409


def test_create_purchase_unknown_supplier_404(client):
    headers, _ = _setup(client)
    resp = client.post(
        "/purchases",
        headers=headers,
        json={
            "supplier_id": "00000000-0000-0000-0000-000000000000",
            "line_items": [{"product_name": "Widget", "qty": "1", "price": "10", "gst_rate": "0"}],
        },
    )
    assert resp.status_code == 404


def test_list_purchases(client):
    headers, supplier_id = _setup(client)
    client.post(
        "/purchases",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "line_items": [{"product_name": "Widget", "qty": "1", "price": "10", "gst_rate": "0"}],
        },
    )
    resp = client.get("/purchases", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["supplier_name"] == "Acme Steel Co"
