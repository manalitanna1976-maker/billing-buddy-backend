from decimal import Decimal


def _setup(client, email="owner@inv.test"):
    signup = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    client.put("/business", headers=headers, json={"state": "Gujarat"})

    customer = client.post(
        "/customers", headers=headers, json={"name": "Acme Traders", "place_of_supply": "Gujarat"}
    )
    return headers, customer.json()["id"]


def test_create_invoice_computes_totals_and_number(client):
    headers, customer_id = _setup(client)

    resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [
                {"product_name": "Steel Rod", "qty": "2", "price": "500", "gst_rate": "18"}
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["invoice_no"] == "1"
    # Pydantic v2 serializes Decimal to a JSON number, not a fixed-format
    # string — compare by value via Decimal, not raw string equality.
    assert Decimal(str(body["taxable_total"])) == Decimal("1000.00")
    assert Decimal(str(body["tax_total"])) == Decimal("180.00")
    assert Decimal(str(body["grand_total"])) == Decimal("1180.00")
    assert len(body["line_items"]) == 1

    second = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Bolt", "qty": "1", "price": "10", "gst_rate": "0"}],
        },
    )
    assert second.json()["invoice_no"] == "2"


def test_list_and_get_invoice(client):
    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice_id = create_resp.json()["id"]

    list_resp = client.get("/invoices", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(f"/invoices/{invoice_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == invoice_id


def test_invoice_cross_tenant_404(client):
    headers_a, customer_id_a = _setup(client, "a@inv.test")
    headers_b, _ = _setup(client, "b@inv.test")

    create_resp = client.post(
        "/invoices",
        headers=headers_a,
        json={
            "customer_id": customer_id_a,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice_id = create_resp.json()["id"]

    resp = client.get(f"/invoices/{invoice_id}", headers=headers_b)
    assert resp.status_code == 404


def test_post_invoices_bad_customer_id_returns_404(client):
    """B0 regression lock: the service raises CustomerNotFoundError, the route
    translates it to HTTP 404 {"detail": "Customer not found"}."""
    headers, _ = _setup(client)

    resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": "00000000-0000-0000-0000-000000000000",
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Customer not found"}


def test_delete_invoice_is_a_soft_cancel(client):
    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice_id = create_resp.json()["id"]
    invoice_no = create_resp.json()["invoice_no"]

    delete_resp = client.delete(f"/invoices/{invoice_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "cancelled"

    # row and invoice_no are retained, not removed — GST numbers must not
    # silently disappear
    get_resp = client.get(f"/invoices/{invoice_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "cancelled"
    assert get_resp.json()["invoice_no"] == invoice_no


def test_duplicate_invoice_no_rejected_by_unique_constraint(client, db_session):
    # Attempt to insert a second row with the same (business_id, invoice_no)
    # directly at the DB layer — this is what the unique index must block,
    # independent of whatever the numbering service does.
    import uuid as uuid_module
    from datetime import date

    from sqlalchemy.exc import IntegrityError

    from app.models import Invoice

    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    original = db_session.query(Invoice).filter(Invoice.invoice_no == create_resp.json()["invoice_no"]).one()

    duplicate = Invoice(
        business_id=original.business_id,
        customer_id=uuid_module.UUID(customer_id),
        invoice_no=original.invoice_no,
        invoice_date=date(2026, 8, 16),
    )
    db_session.add(duplicate)

    try:
        db_session.commit()
        assert False, "expected IntegrityError from unique (business_id, invoice_no) index"
    except IntegrityError:
        db_session.rollback()
