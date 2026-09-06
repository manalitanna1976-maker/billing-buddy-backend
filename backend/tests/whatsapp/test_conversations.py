import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models import Business, WhatsAppConversation
from app.services import whatsapp_conversations as conv_store
from app.services.invoice_ai_parser import ProposedDraft, ProposedLine


def _biz(db):
    b = Business(name="Acme")
    db.add(b)
    db.flush()
    return b


def test_states_frozenset():
    assert conv_store.STATES == {
        "collecting",
        "awaiting_confirm",
        "confirmed",
        "terminal",
    }


def test_get_locked_upserts_once(db_session):
    b = _biz(db_session)
    c1 = conv_store.get_locked(db_session, b.id, "+919000000001")
    c2 = conv_store.get_locked(db_session, b.id, "+919000000001")
    assert c1.id == c2.id
    assert c1.state == "collecting"
    assert c1.draft_payload == {}
    rows = (
        db_session.query(WhatsAppConversation)
        .filter_by(business_id=b.id, sender_phone_e164="+919000000001")
        .all()
    )
    assert len(rows) == 1
    assert c1.expires_at > datetime.utcnow() + timedelta(minutes=25)


def test_get_locked_row_is_lockable(db_session):
    b = _biz(db_session)
    conv_store.get_locked(db_session, b.id, "+919000000002")
    # Re-selecting FOR UPDATE within the same tx must succeed (row exists, locked).
    from sqlalchemy import select

    row = db_session.execute(
        select(WhatsAppConversation)
        .where(
            WhatsAppConversation.business_id == b.id,
            WhatsAppConversation.sender_phone_e164 == "+919000000002",
        )
        .with_for_update()
    ).scalar_one()
    assert row is not None


def test_multi_turn_accumulation(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000003")

    # turn 1: customer only, no line items yet
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[],
            gaps=["line_items"],
        ),
    )
    assert conv.draft_payload["customer_name"] == "Rajesh Traders"
    assert conv.draft_payload.get("line_items", []) == []

    # turn 2: adds a line, no customer mentioned
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name=None,
            line_items=[
                ProposedLine(
                    product_name="Widget",
                    qty=Decimal("2"),
                    price=Decimal("100"),
                    gst_rate=Decimal("18"),
                )
            ],
            gaps=[],
        ),
    )
    assert conv.draft_payload["customer_name"] == "Rajesh Traders"
    assert conv.draft_payload["line_items"] == [
        {"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}
    ]
    assert conv.draft_payload["gaps"] == []


def test_merge_replaces_line_items_wholesale(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000004")
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name="X",
            line_items=[
                ProposedLine("A", Decimal("1"), Decimal("10"), Decimal("0"))
            ],
            gaps=[],
        ),
    )
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name=None,
            line_items=[
                ProposedLine("B", Decimal("3"), Decimal("30"), Decimal("5"))
            ],
            gaps=[],
        ),
    )
    assert [li["product_name"] for li in conv.draft_payload["line_items"]] == ["B"]


def test_merge_keeps_line_items_when_new_parse_has_none(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000041")
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name="X",
            line_items=[ProposedLine("A", Decimal("1"), Decimal("10"), Decimal("0"))],
            gaps=[],
        ),
    )
    # new parse names no line items -> prior list must be kept (else branch)
    conv_store.merge_draft(
        conv,
        ProposedDraft(customer_name="Y", line_items=[], gaps=["something"]),
    )
    assert [li["product_name"] for li in conv.draft_payload["line_items"]] == ["A"]
    assert conv.draft_payload["customer_name"] == "Y"
    assert conv.draft_payload["gaps"] == ["something"]


def test_merge_draft_persists_across_reload(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000042")
    conv_id = conv.id
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("Widget", Decimal("2"), Decimal("100"), Decimal("18"))],
            gaps=["notes"],
            notes="deliver friday",
        ),
    )
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(WhatsAppConversation, conv_id)
    assert reloaded.draft_payload["customer_name"] == "Rajesh Traders"
    assert reloaded.draft_payload["line_items"] == [
        {"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}
    ]
    assert reloaded.draft_payload["notes"] == "deliver friday"
    assert reloaded.draft_payload["gaps"] == ["notes"]


def test_merge_noop_when_confirmed(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000005")
    conv_store.merge_draft(
        conv,
        ProposedDraft(customer_name="Original", line_items=[], gaps=[]),
    )
    conv.state = "confirmed"
    before = dict(conv.draft_payload)
    conv_store.merge_draft(
        conv,
        ProposedDraft(customer_name="Different", line_items=[], gaps=["x"]),
    )
    assert conv.draft_payload == before
    assert conv.draft_payload["customer_name"] == "Original"


def test_is_expired(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000006")
    assert conv_store.is_expired(conv) is False
    future = datetime.utcnow() + timedelta(minutes=999)
    assert conv_store.is_expired(conv, now=future) is True


def test_touch_extends_expiry(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000007")
    conv.expires_at = datetime.utcnow() - timedelta(minutes=1)
    assert conv_store.is_expired(conv) is True
    conv_store.touch(conv)
    assert conv_store.is_expired(conv) is False


def test_to_invoice_create(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000008")
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[
                ProposedLine(
                    product_name="Widget",
                    qty=Decimal("2"),
                    price=Decimal("100.50"),
                    gst_rate=Decimal("18"),
                )
            ],
            gaps=[],
            discount_type="%",
            discount_value=Decimal("10"),
            notes="deliver friday",
        ),
    )
    customer_id = uuid.uuid4()
    ic = conv_store.to_invoice_create(conv, customer_id)
    from datetime import date

    assert ic.customer_id == customer_id
    assert ic.invoice_date == date.today()
    assert len(ic.line_items) == 1
    assert ic.line_items[0].product_name == "Widget"
    assert ic.line_items[0].qty == Decimal("2")
    assert ic.line_items[0].price == Decimal("100.50")
    assert ic.line_items[0].gst_rate == Decimal("18")
    assert ic.discount_type == "%"
    assert ic.discount_value == Decimal("10")
    assert ic.notes == "deliver friday"


def test_to_invoice_create_rejects_bad_customer_id(db_session):
    b = _biz(db_session)
    conv = conv_store.get_locked(db_session, b.id, "+919000000009")
    conv_store.merge_draft(
        conv,
        ProposedDraft(
            customer_name="X",
            line_items=[ProposedLine("A", Decimal("1"), Decimal("10"), Decimal("0"))],
            gaps=[],
        ),
    )
    # pydantic validation still runs on the built payload
    with pytest.raises(Exception):
        conv_store.to_invoice_create(conv, "not-a-uuid")
