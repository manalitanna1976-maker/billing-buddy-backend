"""Task B4: whatsapp_worker.run_once dispatch + retry behaviour."""

from decimal import Decimal

from app.models import Business, Customer, WhatsAppJob
from app.services import whatsapp_flow as flow
from app.services import whatsapp_jobs as jobs
from app.services.invoice_ai_parser import ParserError, ProposedDraft, ProposedLine
from app.services.whatsapp_customer_lookup import Matched
from app.workers import whatsapp_worker as worker


def _biz(db):
    b = Business(name="Acme", state="Gujarat")
    db.add(b)
    db.flush()
    return b


def _cust(db, business):
    c = Customer(business_id=business.id, name="Rajesh Traders", place_of_supply="Gujarat")
    db.add(c)
    db.flush()
    return c


def _inbound_payload(business):
    return {
        "business_id": str(business.id),
        "sender": "+919000000001",
        "wa_message_id": "wamid.1",
        "kind": "text",
        "text": "invoice rajesh 2 widgets 100 each 18% gst",
    }


def test_run_once_false_when_no_jobs(db_session):
    assert worker.run_once(db_session) is False


def test_run_once_inbound_enqueues_outbound_and_completes(db_session, monkeypatch):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("Widget", Decimal("2"), Decimal("100"), Decimal("18"))],
            gaps=[],
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    job = jobs.enqueue(db_session, "inbound_message", _inbound_payload(b))

    assert worker.run_once(db_session) is True

    db_session.expire_all()
    inbound = db_session.get(WhatsAppJob, job.id)
    assert inbound.status == "done"

    outbound = db_session.query(WhatsAppJob).filter_by(type="outbound_send").all()
    assert len(outbound) == 1
    assert outbound[0].business_id == b.id
    assert outbound[0].status == "pending"
    assert outbound[0].payload["kind"] == "buttons"


def test_run_once_parser_error_retries(db_session, monkeypatch):
    b = _biz(db_session)

    def _raise(*a, **k):
        raise ParserError("could not read that")

    monkeypatch.setattr(flow, "parse_message", _raise)

    job = jobs.enqueue(db_session, "inbound_message", _inbound_payload(b))

    assert worker.run_once(db_session) is True

    db_session.expire_all()
    inbound = db_session.get(WhatsAppJob, job.id)
    assert inbound.status == "pending"
    assert inbound.attempts == 1
    assert inbound.last_error is not None
    assert db_session.query(WhatsAppJob).filter_by(type="outbound_send").count() == 0


def test_run_once_parser_error_dead_letters_after_max_attempts(db_session, monkeypatch):
    from app import config

    b = _biz(db_session)

    def _raise(*a, **k):
        raise ParserError("nope")

    monkeypatch.setattr(flow, "parse_message", _raise)

    job = jobs.enqueue(db_session, "inbound_message", _inbound_payload(b))
    max_attempts = config.get_settings().whatsapp_job_max_attempts
    for _ in range(max_attempts):
        worker.run_once(db_session)

    db_session.expire_all()
    inbound = db_session.get(WhatsAppJob, job.id)
    assert inbound.status == "dead_letter"
    assert inbound.attempts == max_attempts


def test_run_once_outbound_send_calls_adapter_and_completes(db_session, monkeypatch):
    from app.models import WhatsAppConnection, WhatsAppMessageLog
    from app.security_crypto import encrypt_secret
    from app.services import whatsapp_client

    b = _biz(db_session)
    db_session.add(
        WhatsAppConnection(
            business_id=b.id,
            phone_number_id="pn1",
            waba_id="waba-1",
            access_token_encrypted=encrypt_secret("tok"),
            status="active",
        )
    )
    db_session.flush()
    monkeypatch.setattr(whatsapp_client, "send_text", lambda conn, to, body: "wamid.out")

    job = jobs.enqueue(
        db_session,
        "outbound_send",
        {"kind": "text", "to": "+919000000001", "business_id": str(b.id), "body": "hi"},
    )

    assert worker.run_once(db_session) is True

    db_session.expire_all()
    assert db_session.get(WhatsAppJob, job.id).status == "done"
    logs = db_session.query(WhatsAppMessageLog).all()
    assert len(logs) == 1 and logs[0].direction == "out"


def test_run_once_unknown_job_type_dead_letters_immediately(db_session):
    """M5: an unknown job type is a poison pill -- dead-letter after ONE
    run_once, don't burn every claim cycle first."""
    job = WhatsAppJob(type="bogus", payload={}, status="pending")
    db_session.add(job)
    db_session.commit()

    assert worker.run_once(db_session) is True

    db_session.expire_all()
    reloaded = db_session.get(WhatsAppJob, job.id)
    assert reloaded.status == "dead_letter"
    assert reloaded.attempts == 1


def test_two_session_double_confirm_one_invoice(db_session):
    """M2: two independent worker sessions each running the confirm path for the
    same conversation produce exactly one invoice (invoice_id latch + the
    commit-before-create ordering)."""
    from app.db import SessionLocal
    from app.models import Invoice
    from app.services import whatsapp_conversations as cs
    from app.services import whatsapp_flow as flow

    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = cs.get_locked(db_session, b.id, "+919000000001")
    conv.state = "awaiting_confirm"
    conv.draft_payload = {
        "customer_name": cust.name,
        "customer_id": str(cust.id),
        "line_items": [{"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}],
        "gaps": [],
    }
    db_session.commit()

    s1, s2 = SessionLocal(), SessionLocal()
    try:
        from app.models import Business

        b1 = s1.get(Business, b.id)
        conv1 = cs.get_locked(s1, b.id, "+919000000001")
        out1 = flow.handle_confirm(s1, conv1, b1)  # creates invoice #1, commits
        assert "created" in out1[0]["body"].lower()

        b2 = s2.get(Business, b.id)
        conv2 = cs.get_locked(s2, b.id, "+919000000001")
        out2 = flow.handle_confirm(s2, conv2, b2)  # sees invoice_id latch -> re-send
        assert out2 == [conv2.last_result_payload]
    finally:
        s1.close()
        s2.close()

    assert db_session.query(Invoice).count() == 1


def test_run_once_outbound_send_no_connection_retries(db_session):
    b = _biz(db_session)
    job = jobs.enqueue(
        db_session,
        "outbound_send",
        {"kind": "text", "to": "+919000000001", "business_id": str(b.id), "body": "hi"},
    )

    assert worker.run_once(db_session) is True

    db_session.expire_all()
    reloaded = db_session.get(WhatsAppJob, job.id)
    assert reloaded.status == "pending"
    assert reloaded.last_error is not None
