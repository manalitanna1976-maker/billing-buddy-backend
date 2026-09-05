import datetime as dt

import pytest

from app.models import Business, Customer
from app.schemas.invoice import InvoiceCreate
from app.services.invoices import CustomerNotFoundError, create_invoice_for_business


def _seed(db):
    biz = Business(name="Acme", state="Gujarat", invoice_prefix="INV-", next_invoice_seq=1)
    db.add(biz)
    db.flush()
    cust = Customer(business_id=biz.id, name="ABC Corp", place_of_supply="Gujarat")
    db.add(cust)
    db.flush()
    return biz, cust


def test_create_invoice_for_business_creates_invoice_with_number_and_totals(db_session):
    biz, cust = _seed(db_session)
    body = InvoiceCreate(
        customer_id=cust.id,
        invoice_date=dt.date(2026, 8, 17),
        line_items=[{"product_name": "Widget", "qty": 10, "price": 500, "gst_rate": 18}],
    )

    invoice = create_invoice_for_business(db_session, biz, body)
    db_session.commit()

    assert invoice.invoice_no == "INV-1"
    assert invoice.taxable_total == 5000
    assert invoice.tax_total == 900
    assert invoice.grand_total == 5900
    assert len(invoice.line_items) == 1


def test_create_invoice_for_business_rejects_foreign_customer(db_session):
    biz, _ = _seed(db_session)
    other = Business(name="Other", state="Gujarat")
    db_session.add(other)
    db_session.flush()
    foreign = Customer(business_id=other.id, name="Not Yours")
    db_session.add(foreign)
    db_session.flush()

    body = InvoiceCreate(
        customer_id=foreign.id,
        invoice_date=dt.date(2026, 8, 17),
        line_items=[{"product_name": "X", "qty": 1, "price": 1, "gst_rate": 0}],
    )
    with pytest.raises(CustomerNotFoundError):
        create_invoice_for_business(db_session, biz, body)


def test_create_invoice_for_business_does_not_commit(db_session):
    biz, cust = _seed(db_session)
    body = InvoiceCreate(
        customer_id=cust.id,
        invoice_date=dt.date(2026, 8, 17),
        line_items=[{"product_name": "Widget", "qty": 1, "price": 100, "gst_rate": 18}],
    )
    create_invoice_for_business(db_session, biz, body)
    db_session.rollback()
    from app.models import Invoice
    assert db_session.query(Invoice).count() == 0
