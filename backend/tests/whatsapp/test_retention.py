"""Task B6: whatsapp_retention.retention_sweep -- periodic PII/garbage cleanup."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from app.models import (
    Business,
    Customer,
    Invoice,
    RevokedToken,
    WhatsAppConversation,
    WhatsAppJob,
    WhatsAppMessageLog,
)
from app.services.whatsapp_retention import retention_sweep


def _biz(db):
    b = Business(name="Acme")
    db.add(b)
    db.flush()
    return b


def _invoice(db, business):
    cust = Customer(business_id=business.id, name="C")
    db.add(cust)
    db.flush()
    inv = Invoice(
        business_id=business.id, customer_id=cust.id, invoice_no="1",
        invoice_date=date.today(), grand_total=Decimal("1"),
    )
    db.add(inv)
    db.flush()
    return inv


def _conv(db, business, sender, *, state="collecting", expires_at, updated_at, invoice_id=None):
    c = WhatsAppConversation(
        business_id=business.id,
        sender_phone_e164=sender,
        state=state,
        draft_payload={},
        invoice_id=invoice_id,
        expires_at=expires_at,
        updated_at=updated_at,
        created_at=updated_at,
    )
    db.add(c)
    db.flush()
    return c


def test_retention_deletes_expired_and_old_confirmed(db_session):
    b = _biz(db_session)
    now = datetime.utcnow()

    expired = _conv(
        db_session, b, "+91900000001",
        expires_at=now - timedelta(hours=25), updated_at=now - timedelta(hours=25),
    )
    old_confirmed = _conv(
        db_session, b, "+91900000002", state="confirmed",
        invoice_id=_invoice(db_session, b).id,
        expires_at=now + timedelta(hours=1), updated_at=now - timedelta(hours=25),
    )
    fresh = _conv(
        db_session, b, "+91900000003",
        expires_at=now + timedelta(hours=1), updated_at=now - timedelta(minutes=5),
    )
    db_session.commit()

    counts = retention_sweep(db_session)

    db_session.expire_all()
    remaining = {c.id for c in db_session.query(WhatsAppConversation).all()}
    assert remaining == {fresh.id}
    assert counts["conversations"] == 2


def test_retention_resets_stranded_confirms(db_session):
    b = _biz(db_session)
    now = datetime.utcnow()

    stranded = _conv(
        db_session, b, "+91900000010", state="confirmed", invoice_id=None,
        expires_at=now + timedelta(hours=5), updated_at=now - timedelta(minutes=30),
    )
    recent_confirm = _conv(
        db_session, b, "+91900000011", state="confirmed", invoice_id=None,
        expires_at=now + timedelta(hours=5), updated_at=now - timedelta(minutes=2),
    )
    db_session.commit()

    counts = retention_sweep(db_session)

    db_session.expire_all()
    assert db_session.get(WhatsAppConversation, stranded.id).state == "terminal"
    assert db_session.get(WhatsAppConversation, recent_confirm.id).state == "confirmed"
    assert counts["stranded_confirms"] == 1


def test_retention_resets_collecting_row_with_invoice_id(db_session):
    """I2 belt-and-braces: a non-terminal row stuck at state='collecting' WITH
    invoice_id set (the confirm split-window race) and idle past 15 min is reset
    to terminal by the sweep."""
    b = _biz(db_session)
    now = datetime.utcnow()
    inv_id = _invoice(db_session, b).id

    stuck = _conv(
        db_session, b, "+91900000040", state="collecting", invoice_id=inv_id,
        expires_at=now + timedelta(hours=5), updated_at=now - timedelta(minutes=30),
    )
    fresh_collecting = _conv(
        db_session, b, "+91900000041", state="collecting", invoice_id=inv_id,
        expires_at=now + timedelta(hours=5), updated_at=now - timedelta(minutes=2),
    )
    db_session.commit()

    counts = retention_sweep(db_session)

    db_session.expire_all()
    assert db_session.get(WhatsAppConversation, stuck.id).state == "terminal"
    assert db_session.get(WhatsAppConversation, fresh_collecting.id).state == "collecting"
    assert counts["stranded_confirms"] == 1


def test_retention_message_log_never_has_body(db_session):
    b = _biz(db_session)
    now = datetime.utcnow()

    gone_conv_id = _conv(
        db_session, b, "+91900000020",
        expires_at=now - timedelta(hours=48), updated_at=now - timedelta(hours=48),
    ).id
    live_conv = _conv(
        db_session, b, "+91900000021",
        expires_at=now + timedelta(hours=1), updated_at=now,
    )
    db_session.flush()

    orphan = WhatsAppMessageLog(
        wa_message_id="wamid.orphan", direction="out", conversation_id=gone_conv_id
    )
    kept = WhatsAppMessageLog(
        wa_message_id="wamid.kept", direction="in", conversation_id=live_conv.id
    )
    unlinked = WhatsAppMessageLog(wa_message_id="wamid.unlinked", direction="out")
    db_session.add_all([orphan, kept, unlinked])
    db_session.commit()

    assert "body" not in {c.name for c in WhatsAppMessageLog.__table__.columns}

    counts = retention_sweep(db_session)

    db_session.expire_all()
    left = {m.wa_message_id for m in db_session.query(WhatsAppMessageLog).all()}
    assert left == {"wamid.kept", "wamid.unlinked"}
    assert counts["message_logs"] == 1


def test_retention_deletes_old_done_and_dead_letter_jobs(db_session):
    b = _biz(db_session)
    now = datetime.utcnow()

    done_old = WhatsAppJob(
        type="inbound_message",
        payload={"text": "invoice rajesh 2 widgets 100 GSTIN 24ABCDE1234F1Z5"},
        status="done",
        business_id=b.id,
        created_at=now - timedelta(hours=30),
        processed_at=now - timedelta(hours=25),
    )
    dead_old = WhatsAppJob(
        type="outbound_send",
        payload={"kind": "document"},
        status="dead_letter",
        business_id=b.id,
        created_at=now - timedelta(hours=25),
        processed_at=None,
    )
    pending_fresh = WhatsAppJob(
        type="inbound_message",
        payload={"text": "fresh"},
        status="pending",
        business_id=b.id,
        created_at=now - timedelta(minutes=1),
    )
    done_fresh = WhatsAppJob(
        type="inbound_message",
        payload={"text": "recent"},
        status="done",
        business_id=b.id,
        created_at=now - timedelta(hours=1),
        processed_at=now - timedelta(minutes=30),
    )
    db_session.add_all([done_old, dead_old, pending_fresh, done_fresh])
    db_session.commit()

    counts = retention_sweep(db_session)

    db_session.expire_all()
    left = {j.status for j in db_session.query(WhatsAppJob).all()}
    ids = {j.id for j in db_session.query(WhatsAppJob).all()}
    assert ids == {pending_fresh.id, done_fresh.id}
    assert left == {"pending", "done"}
    assert counts["jobs"] == 2


def test_retention_folds_in_prereq_sweeps(db_session):
    now = datetime.utcnow()
    db_session.add(RevokedToken(jti="expired-jti", expires_at=now - timedelta(hours=1)))
    db_session.add(RevokedToken(jti="live-jti", expires_at=now + timedelta(hours=1)))
    db_session.commit()

    counts = retention_sweep(db_session)

    db_session.expire_all()
    jtis = {r.jti for r in db_session.query(RevokedToken).all()}
    assert jtis == {"live-jti"}
    assert counts["revoked_tokens"] == 1
    assert "rate_limit_events" in counts
