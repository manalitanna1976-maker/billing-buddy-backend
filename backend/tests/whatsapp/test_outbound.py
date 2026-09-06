"""Task B6: whatsapp_outbound.handle_outbound -- the real Meta adapter send."""

from datetime import date
from decimal import Decimal

import pytest

from app.models import (
    Business,
    Customer,
    Invoice,
    WhatsAppConnection,
    WhatsAppJob,
    WhatsAppMessageLog,
)
from app.security_crypto import encrypt_secret
from app.services import pdf as pdf_service
from app.services import whatsapp_client
from app.services import whatsapp_jobs as jobs
from app.services import whatsapp_outbound as outbound
from app.services.whatsapp_client import WhatsAppSendError


def _biz(db):
    b = Business(name="Acme", state="Gujarat")
    db.add(b)
    db.flush()
    return b


def _conn(db, business, status="active", token="EAAtoken"):
    c = WhatsAppConnection(
        business_id=business.id,
        phone_number_id="pn-123",
        waba_id="waba-1",
        access_token_encrypted=encrypt_secret(token),
        status=status,
    )
    db.add(c)
    db.flush()
    return c


def _invoice(db, business):
    cust = Customer(business_id=business.id, name="Rajesh Traders", place_of_supply="Gujarat")
    db.add(cust)
    db.flush()
    inv = Invoice(
        business_id=business.id,
        customer_id=cust.id,
        invoice_no="42",
        invoice_date=date.today(),
        grand_total=Decimal("236.00"),
    )
    db.add(inv)
    db.flush()
    return inv


def _job(db, business, payload: dict) -> WhatsAppJob:
    return jobs.enqueue(db, "outbound_send", payload, business_id=business.id)


def test_outbound_text_calls_adapter(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b, token="secret-tok")
    job = _job(
        db_session, b,
        {"kind": "text", "to": "+919000000001", "business_id": str(b.id), "body": "hi there"},
    )

    seen = {}

    def fake_send_text(conn, to, body):
        seen.update(conn=conn, to=to, body=body)
        return "wamid.out1"

    monkeypatch.setattr(whatsapp_client, "send_text", fake_send_text)

    outbound.handle_outbound(db_session, job)

    assert seen["to"] == "+919000000001"
    assert seen["body"] == "hi there"
    assert seen["conn"].phone_number_id == "pn-123"
    assert seen["conn"].access_token == "secret-tok"  # decrypted

    db_session.expire_all()
    assert db_session.get(WhatsAppJob, job.id).status == "done"
    logs = db_session.query(WhatsAppMessageLog).all()
    assert len(logs) == 1
    assert logs[0].wa_message_id == "wamid.out1"
    assert logs[0].direction == "out"
    assert not hasattr(logs[0], "body")


def test_outbound_buttons_calls_adapter(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b)
    job = _job(
        db_session, b,
        {
            "kind": "buttons",
            "to": "+919000000001",
            "business_id": str(b.id),
            "body": "confirm?",
            "buttons": [["wa_confirm", "Confirm"], ["wa_edit", "Edit"]],
        },
    )

    seen = {}
    monkeypatch.setattr(
        whatsapp_client,
        "send_buttons",
        lambda conn, to, body, buttons: seen.update(buttons=buttons) or "wamid.b1",
    )

    outbound.handle_outbound(db_session, job)

    # JSONB round-trips tuples as lists; handler must re-tuple them.
    assert seen["buttons"] == [("wa_confirm", "Confirm"), ("wa_edit", "Edit")]
    assert db_session.query(WhatsAppMessageLog).count() == 1


def test_outbound_document_renders_uploads_and_default_caption(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b)
    inv = _invoice(db_session, b)
    job = _job(
        db_session, b,
        {
            "kind": "document",
            "to": "+919000000001",
            "business_id": str(b.id),
            "invoice_id": str(inv.id),
        },
    )

    calls = []
    monkeypatch.setattr(pdf_service, "render_invoice_pdf", lambda invoice: b"%PDF-1.4 fake")
    monkeypatch.setattr(
        whatsapp_client,
        "upload_media",
        lambda conn, content, filename, mime: calls.append(("upload", content, filename, mime))
        or "media-99",
    )
    monkeypatch.setattr(
        whatsapp_client,
        "send_document",
        lambda conn, to, media_id, filename, caption=None: calls.append(
            ("send", media_id, filename, caption)
        )
        or "wamid.doc1",
    )

    outbound.handle_outbound(db_session, job)

    assert calls[0] == ("upload", b"%PDF-1.4 fake", "42.pdf", "application/pdf")
    # no caption in the payload -> a default derived from the invoice number
    assert calls[1] == ("send", "media-99", "42.pdf", "Invoice 42")
    log = db_session.query(WhatsAppMessageLog).one()
    assert log.wa_message_id == "wamid.doc1"
    assert log.direction == "out"


def test_outbound_document_keeps_explicit_caption(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b)
    inv = _invoice(db_session, b)
    job = _job(
        db_session, b,
        {
            "kind": "document",
            "to": "+919000000001",
            "business_id": str(b.id),
            "invoice_id": str(inv.id),
            "caption": "Your invoice, thanks!",
        },
    )
    seen = {}
    monkeypatch.setattr(pdf_service, "render_invoice_pdf", lambda invoice: b"%PDF")
    monkeypatch.setattr(whatsapp_client, "upload_media", lambda *a, **k: "m1")
    monkeypatch.setattr(
        whatsapp_client,
        "send_document",
        lambda conn, to, media_id, filename, caption=None: seen.update(caption=caption)
        or "wamid.d2",
    )

    outbound.handle_outbound(db_session, job)

    assert seen["caption"] == "Your invoice, thanks!"


def test_outbound_no_active_connection_raises(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b, status="disconnected")
    job = _job(
        db_session, b,
        {"kind": "text", "to": "+919000000001", "business_id": str(b.id), "body": "hi"},
    )

    monkeypatch.setattr(whatsapp_client, "send_text", lambda *a, **k: "x")

    with pytest.raises(RuntimeError):
        outbound.handle_outbound(db_session, job)


def test_outbound_then_document_enqueues_followup_atomically(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b)
    inv = _invoice(db_session, b)
    job = _job(
        db_session, b,
        {
            "kind": "text",
            "to": "+919000000001",
            "business_id": str(b.id),
            "body": "Invoice 42 created.",
            "then_document_invoice_id": str(inv.id),
        },
    )

    monkeypatch.setattr(whatsapp_client, "send_text", lambda *a, **k: "wamid.t1")

    outbound.handle_outbound(db_session, job)

    db_session.expire_all()
    assert db_session.get(WhatsAppJob, job.id).status == "done"
    followup = (
        db_session.query(WhatsAppJob)
        .filter(WhatsAppJob.type == "outbound_send", WhatsAppJob.status == "pending")
        .all()
    )
    assert len(followup) == 1
    p = followup[0].payload
    assert p["kind"] == "document"
    assert p["invoice_id"] == str(inv.id)
    assert p["to"] == "+919000000001"
    assert followup[0].business_id == b.id


def test_outbound_send_failure_propagates_no_log_no_completion(db_session, monkeypatch):
    b = _biz(db_session)
    _conn(db_session, b)
    job = _job(
        db_session, b,
        {"kind": "text", "to": "+919000000001", "business_id": str(b.id), "body": "hi"},
    )

    def _boom(*a, **k):
        raise WhatsAppSendError(500, "meta down")

    monkeypatch.setattr(whatsapp_client, "send_text", _boom)

    with pytest.raises(WhatsAppSendError):
        outbound.handle_outbound(db_session, job)
    db_session.rollback()
    assert db_session.query(WhatsAppMessageLog).count() == 0
    # handle_outbound never marked it done -> run_once's except -> fail() retries.
    assert db_session.get(WhatsAppJob, job.id).status == "pending"


def test_outbound_send_failure_retried_no_second_invoice(db_session, monkeypatch):
    """send_document raising -> job re-queued (pending), invoice count unchanged."""
    from app.workers import whatsapp_worker as worker

    b = _biz(db_session)
    _conn(db_session, b)
    inv = _invoice(db_session, b)
    db_session.commit()

    monkeypatch.setattr(pdf_service, "render_invoice_pdf", lambda invoice: b"%PDF")
    monkeypatch.setattr(whatsapp_client, "upload_media", lambda *a, **k: "m1")

    def _boom(*a, **k):
        raise WhatsAppSendError(503, "unavailable")

    monkeypatch.setattr(whatsapp_client, "send_document", _boom)

    job = jobs.enqueue(
        db_session,
        "outbound_send",
        {"kind": "document", "to": "+919000000001", "business_id": str(b.id), "invoice_id": str(inv.id)},
        business_id=b.id,
    )

    assert worker.run_once(db_session) is True

    db_session.expire_all()
    assert db_session.get(WhatsAppJob, job.id).status == "pending"
    assert db_session.query(Invoice).count() == 1
