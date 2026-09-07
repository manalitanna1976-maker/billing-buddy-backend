"""Regression tests for the 2026-09-07 QA pass fixes (FB-1..14, NF-1..5)."""

from datetime import date, timedelta

import pytest

VALID_GSTIN = "27AAPFU0939F1ZV"


def _headers(client, email="qa@fix.test", state="27-Maharashtra"):
    r = client.post(
        "/auth/signup",
        json={"business_name": "Fix Co", "email": email, "password": "pass1234"},
    )
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.put("/business", headers=h, json={"state": state, "gstin": VALID_GSTIN})
    return h


def _customer(client, h, name="Acme Corp", place="27-Maharashtra"):
    r = client.post(
        "/customers", headers=h, json={"name": name, "place_of_supply": place}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _line(**kw):
    base = {"product_name": "Widget", "qty": "1", "price": "100", "gst_rate": "18"}
    base.update(kw)
    return base


def _invoice_body(customer_id, **kw):
    body = {
        "customer_id": customer_id,
        "invoice_date": date.today().isoformat(),
        "line_items": [_line()],
    }
    body.update(kw)
    return body


# --- FB-5: out-of-range / bad-enum input -> 422, never 500 ------------------- #

@pytest.mark.parametrize(
    "patch",
    [
        {"line_items": [_line(gst_rate="9999")]},
        {"line_items": [_line(qty="0")]},
        {"line_items": [_line(qty="-5")]},
        {"line_items": [_line(price="-100")]},
        {"line_items": [_line(price="1e30")]},
        {"discount_type": "HACK"},
        {"payment_type": "bitcoin"},
        {"invoice_type": "Nonsense"},
        {"line_items": []},
        {"discount_type": "%", "discount_value": "150"},
    ],
)
def test_bad_invoice_input_is_422(client, patch):
    h = _headers(client, email=f"v{abs(hash(str(patch)))%99999}@fix.test")
    cid = _customer(client, h)
    r = client.post("/invoices", headers=h, json=_invoice_body(cid, **patch))
    assert r.status_code == 422, r.text


def test_far_future_invoice_date_is_422(client):
    h = _headers(client, email="future@fix.test")
    cid = _customer(client, h)
    body = _invoice_body(cid, invoice_date=(date.today() + timedelta(days=400)).isoformat())
    assert client.post("/invoices", headers=h, json=body).status_code == 422


# --- FB-6: unknown / foreign bank_account_id -> 404 ------------------------- #

def test_unknown_bank_account_is_404(client):
    h = _headers(client, email="bank@fix.test")
    cid = _customer(client, h)
    body = _invoice_body(cid, bank_account_id="11111111-1111-1111-1111-111111111111")
    r = client.post("/invoices", headers=h, json=body)
    assert r.status_code == 404
    assert r.json()["detail"] == "Bank account not found"


def test_foreign_bank_account_is_404(client):
    ha = _headers(client, email="ba@fix.test")
    hb = _headers(client, email="bb@fix.test")
    acc = client.post(
        "/bank-accounts",
        headers=hb,
        json={"bank_name": "HDFC", "account_no": "123", "ifsc": "HDFC0001234"},
    ).json()["id"]
    cid = _customer(client, ha)
    body = _invoice_body(cid, bank_account_id=acc)
    assert client.post("/invoices", headers=ha, json=body).status_code == 404


# --- FB-8: customer validation -------------------------------------------- #

@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": "ok", "gstin": "NOTVALID"},
        {"name": "ok", "pan": "abc"},
    ],
)
def test_bad_customer_input_is_422(client, payload):
    h = _headers(client, email=f"c{abs(hash(str(payload)))%99999}@fix.test")
    assert client.post("/customers", headers=h, json=payload).status_code == 422


def test_valid_gstin_pan_normalised_uppercase(client):
    h = _headers(client, email="norm@fix.test")
    r = client.post(
        "/customers",
        headers=h,
        json={"name": "X", "gstin": "27aapfu0939f1zv", "pan": "aapfu0939f"},
    )
    assert r.status_code == 201
    assert r.json()["gstin"] == "27AAPFU0939F1ZV"
    assert r.json()["pan"] == "AAPFU0939F"


# --- FB-1: intra/inter-state GST classification -------------------------- #

def test_intra_state_tolerant_match_gives_cgst_sgst(client):
    h = _headers(client, email="intra@fix.test", state="Maharashtra")
    cid = _customer(client, h, place="27-Maharashtra")
    r = client.post("/invoices", headers=h, json=_invoice_body(cid))
    assert r.status_code == 201, r.text
    j = r.json()
    assert float(j["igst_total"]) == 0
    assert float(j["cgst_total"]) > 0 and float(j["sgst_total"]) > 0


def test_inter_state_gives_igst(client):
    h = _headers(client, email="inter@fix.test", state="27-Maharashtra")
    cid = _customer(client, h, place="24-Gujarat")
    j = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()
    assert float(j["cgst_total"]) == 0 and float(j["sgst_total"]) == 0
    assert float(j["igst_total"]) > 0


# --- FB-2: GST split persisted + rendered -------------------------------- #

def test_invoice_read_exposes_gst_split(client):
    h = _headers(client, email="split@fix.test")
    cid = _customer(client, h)
    j = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()
    for k in ("cgst_total", "sgst_total", "igst_total", "discount_amount", "round_off_amount"):
        assert k in j


def test_pdf_shows_cgst_sgst_rows(client):
    h = _headers(client, email="pdf@fix.test")
    cid = _customer(client, h)
    iid = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()["id"]
    from app.db import SessionLocal
    from app.models import Invoice
    from app.services.pdf import render_invoice_html

    db = SessionLocal()
    try:
        html = render_invoice_html(db.get(Invoice, iid))
    finally:
        db.close()
    assert "CGST" in html and "SGST" in html


# --- FB-3: bill-to snapshot --------------------------------------------- #

def test_invoice_snapshots_bill_to_and_survives_customer_edit(client):
    h = _headers(client, email="snap@fix.test")
    cid = _customer(client, h, name="Original Name")
    iid = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()["id"]
    assert client.get(f"/invoices/{iid}", headers=h).json()["bill_to_name"] == "Original Name"

    client.put(f"/customers/{cid}", headers=h, json={"name": "Renamed Later"})
    j = client.get(f"/invoices/{iid}", headers=h).json()
    assert j["bill_to_name"] == "Original Name"  # snapshot unchanged


# --- FB-4 / FB-10: lifecycle ------------------------------------------- #

def test_finalize_then_locked(client):
    h = _headers(client, email="final@fix.test")
    cid = _customer(client, h)
    iid = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()["id"]

    fr = client.post(f"/invoices/{iid}/finalize", headers=h)
    assert fr.status_code == 200 and fr.json()["status"] == "saved"

    # editing a finalized invoice is rejected
    assert client.put(f"/invoices/{iid}", headers=h, json=_invoice_body(cid)).status_code == 409
    # re-finalize is a no-op 200
    assert client.post(f"/invoices/{iid}/finalize", headers=h).status_code == 200


def test_cancelled_invoice_is_immutable(client):
    h = _headers(client, email="cancel@fix.test")
    cid = _customer(client, h)
    iid = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()["id"]

    assert client.delete(f"/invoices/{iid}", headers=h).status_code == 200
    assert client.put(f"/invoices/{iid}", headers=h, json=_invoice_body(cid)).status_code == 409
    assert client.delete(f"/invoices/{iid}", headers=h).status_code == 409


# --- FB-13: cancelled PDF watermark ----------------------------------- #

def test_cancelled_pdf_has_watermark(client):
    h = _headers(client, email="wm@fix.test")
    cid = _customer(client, h)
    iid = client.post("/invoices", headers=h, json=_invoice_body(cid)).json()["id"]
    client.delete(f"/invoices/{iid}", headers=h)
    from app.db import SessionLocal
    from app.models import Invoice
    from app.services.pdf import render_invoice_html

    db = SessionLocal()
    try:
        html = render_invoice_html(db.get(Invoice, iid))
    finally:
        db.close()
    assert "CANCELLED" in html


# --- NF-1 / NF-2: list projection + pagination ------------------------ #

def test_list_has_customer_name_and_total(client):
    h = _headers(client, email="list@fix.test")
    cid = _customer(client, h, name="Listed Co")
    client.post("/invoices", headers=h, json=_invoice_body(cid))
    client.post("/invoices", headers=h, json=_invoice_body(cid))

    r = client.get("/invoices?limit=1&offset=0", headers=h).json()
    assert r["total"] == 2
    assert len(r["items"]) == 1
    assert r["items"][0]["customer_name"] == "Listed Co"
    assert r["limit"] == 1


# --- NF-5: signup rate limit ----------------------------------------- #

def test_signup_rate_limited_per_ip(client):
    codes = [
        client.post(
            "/auth/signup",
            json={"business_name": "S", "email": f"rl{i}@fix.test", "password": "pass1234"},
        ).status_code
        for i in range(22)
    ]
    assert 429 in codes


# --- meta/states ---------------------------------------------------- #

def test_meta_states(client):
    r = client.get("/meta/states")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 37
    assert {"code": "27", "name": "Maharashtra", "value": "27-Maharashtra"} in data
