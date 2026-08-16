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


def test_download_invoice_pdf_without_logo_still_generates(client):
    # _setup never uploads a logo — this is the "business hasn't customized
    # yet" path the default wordmark fallback exists for. The PDF must
    # still render successfully rather than leaving blank/broken markup.
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

    resp = client.get(f"/invoices/{invoice_id}/pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.content[:4] == b"%PDF"


def test_invoice_html_shows_default_logo_fallback_when_no_logo_uploaded(client, db_session):
    from app.models import Invoice
    from app.services.pdf import render_invoice_html

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
    invoice = db_session.get(Invoice, create_resp.json()["id"])

    html = render_invoice_html(invoice)
    assert 'class="logo-fallback"' in html
    assert "Billing Buddy" in html
    assert '<img class="logo"' not in html


def test_invoice_html_hides_default_logo_fallback_when_logo_uploaded(client, db_session, tmp_path, monkeypatch):
    import io

    from app.models import Invoice
    from app.services.pdf import render_invoice_html

    monkeypatch.chdir(tmp_path)
    headers, customer_id = _setup(client)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("logo.png", io.BytesIO(png_bytes), "image/png")},
    )

    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice = db_session.get(Invoice, create_resp.json()["id"])

    html = render_invoice_html(invoice)
    assert '<img class="logo"' in html
    assert 'class="logo-fallback"' not in html

    # The rendered <img> src must resolve to the file actually written to
    # disk by the upload endpoint — not a path with a duplicated "uploads"
    # segment that WeasyPrint would silently fail to load.
    import re
    from pathlib import Path

    match = re.search(r'<img class="logo" src="file://([^"]+)">', html)
    assert match is not None
    assert Path(match.group(1)).is_file()
