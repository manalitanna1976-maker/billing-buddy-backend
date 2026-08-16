def _setup(client, email="owner@pdf.test"):
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


def test_download_invoice_pdf(client):
    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "2", "price": "500", "gst_rate": "18"}],
        },
    )
    invoice_id = create_resp.json()["id"]
    invoice_no = create_resp.json()["invoice_no"]

    resp = client.get(f"/invoices/{invoice_id}/pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert f'filename="{invoice_no}.pdf"' in resp.headers["content-disposition"]
    assert resp.content[:4] == b"%PDF"
