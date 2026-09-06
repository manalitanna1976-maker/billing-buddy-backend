"""Task B4: whatsapp_flow.handle_inbound decision logic.

parse_message (B1) and resolve (B3) are monkeypatched on the flow module so
these tests exercise ONLY the branch logic that turns an inbound message into a
slot-fill question or a confirm prompt. The confirm->create path is Task B5.
"""

from decimal import Decimal

from app.models import Business, Customer, Invoice, WhatsAppConversation
from app.services import whatsapp_flow as flow
from app.services.invoice_ai_parser import ProposedDraft, ProposedLine
from app.services.whatsapp_customer_lookup import Ambiguous, Matched, NotFound


def _biz(db, state="Gujarat"):
    b = Business(name="Acme", state=state)
    db.add(b)
    db.flush()
    return b


def _cust(db, business, name="Rajesh Traders", gstin=None, pos="Gujarat"):
    c = Customer(business_id=business.id, name=name, gstin=gstin, place_of_supply=pos)
    db.add(c)
    db.flush()
    return c


def _payload(business, *, sender="+919000000001", **extra):
    p = {
        "business_id": str(business.id),
        "sender": sender,
        "wa_message_id": "wamid.test",
        "kind": "text",
        "text": "some message",
    }
    p.update(extra)
    return p


def _full_draft(customer_name="Rajesh Traders"):
    return ProposedDraft(
        customer_name=customer_name,
        line_items=[ProposedLine("Widget", Decimal("2"), Decimal("100"), Decimal("18"))],
        gaps=[],
    )


def _conv(db, business, sender="+919000000001"):
    from app.services import whatsapp_conversations as cs

    return cs.get_locked(db, business.id, sender)


# --------------------------------------------------------------------------- #
# text: gap -> one question, stay collecting, nothing created
# --------------------------------------------------------------------------- #
def test_text_with_gap_asks_one_question(db_session, monkeypatch):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders", line_items=[], gaps=["What are you invoicing?"]
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert out[0]["to"] == "+919000000001"
    assert out[0]["business_id"] == str(b.id)
    assert out[0]["body"] == "What are you invoicing?"

    conv = _conv(db_session, b)
    assert conv.state == "collecting"
    assert db_session.query(Invoice).count() == 0


def test_no_customer_named_is_a_gap_and_resolve_not_called(db_session, monkeypatch):
    b = _biz(db_session)
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name=None,
            line_items=[ProposedLine("Widget", Decimal("2"), Decimal("100"), Decimal("18"))],
            gaps=[],
        ),
    )

    def _boom(*a, **k):
        raise AssertionError("resolve must not be called without a customer name")

    monkeypatch.setattr(flow, "resolve", _boom)

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "customer" in out[0]["body"].lower()
    assert _conv(db_session, b).state == "collecting"


def test_first_gap_question_flags_missing_product_name():
    """M4: a line item with no product_name is a gap (asked), never allowed
    through to handle_confirm where to_invoice_create would KeyError."""
    for bad in (None, "", "   "):
        payload = {
            "gaps": [],
            "line_items": [{"product_name": bad, "qty": "2", "price": "100", "gst_rate": "18"}],
        }
        q = flow._first_gap_question(payload)
        assert q is not None
        assert "invoicing" in q.lower()

    # a fully-formed line is still ready (None)
    ok = {
        "gaps": [],
        "line_items": [{"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}],
    }
    assert flow._first_gap_question(ok) is None


def test_synthesized_question_when_line_incomplete_and_no_gap(db_session, monkeypatch):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("Widget", Decimal("2"), Decimal("0"), Decimal("18"))],
            gaps=[],
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "price" in out[0]["body"].lower()
    assert "Widget" in out[0]["body"]
    assert _conv(db_session, b).state == "collecting"


# --------------------------------------------------------------------------- #
# text: unknown customer -> terminal, nothing written
# --------------------------------------------------------------------------- #
def test_unknown_customer_goes_terminal(db_session, monkeypatch):
    b = _biz(db_session)
    _cust(db_session, b)  # a real customer exists, but not the one named
    monkeypatch.setattr(flow, "parse_message", lambda text, prior: _full_draft("Nobody Ltd"))
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: NotFound())

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "Nobody Ltd" in out[0]["body"]
    assert "web app" in out[0]["body"]
    assert _conv(db_session, b).state == "terminal"
    assert db_session.query(Invoice).count() == 0
    assert db_session.query(Customer).count() == 1


# --------------------------------------------------------------------------- #
# text: ambiguous customer -> list candidates, stay collecting
# --------------------------------------------------------------------------- #
def test_ambiguous_customer_lists_candidates(db_session, monkeypatch):
    b = _biz(db_session)
    c1 = _cust(db_session, b, name="Rajesh Traders")
    c2 = _cust(db_session, b, name="Rajesh Textiles")
    monkeypatch.setattr(flow, "parse_message", lambda text, prior: _full_draft("Rajesh"))
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Ambiguous(candidates=[c1, c2]))

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "Rajesh Traders" in out[0]["body"]
    assert "Rajesh Textiles" in out[0]["body"]
    assert "exact name" in out[0]["body"]
    assert _conv(db_session, b).state == "collecting"


# --------------------------------------------------------------------------- #
# text: complete draft + matched customer -> awaiting_confirm + buttons
# --------------------------------------------------------------------------- #
def test_complete_draft_goes_awaiting_confirm(db_session, monkeypatch):
    b = _biz(db_session, state="Gujarat")
    cust = _cust(db_session, b, name="Rajesh Traders", gstin="24AAAAA0000A1Z5", pos="Gujarat")
    monkeypatch.setattr(flow, "parse_message", lambda text, prior: _full_draft())
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    p = out[0]
    assert p["kind"] == "buttons"
    assert p["buttons"] == [("wa_confirm", "Confirm"), ("wa_edit", "Edit")]
    assert "Rajesh Traders" in p["body"]
    assert "24AAAAA0000A1Z5" in p["body"]
    assert "236.00" in p["body"]  # 200 taxable + 18% GST, round_off
    assert "confirm?" in p["body"].lower()

    conv = _conv(db_session, b)
    assert conv.state == "awaiting_confirm"
    assert db_session.query(Invoice).count() == 0


def test_matched_customer_id_stored_and_persisted(db_session, monkeypatch):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    monkeypatch.setattr(flow, "parse_message", lambda text, prior: _full_draft())
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    flow.handle_inbound(db_session, _payload(b))
    conv_id = _conv(db_session, b).id
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(WhatsAppConversation, conv_id)
    assert reloaded.draft_payload["customer_id"] == str(cust.id)


# --------------------------------------------------------------------------- #
# button branches
# --------------------------------------------------------------------------- #
def test_button_edit_resets_to_collecting(db_session):
    b = _biz(db_session)
    conv = _conv(db_session, b)
    conv.state = "awaiting_confirm"

    out = flow.handle_inbound(
        db_session, _payload(b, kind="button", button_id="wa_edit", text=None)
    )

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "corrected" in out[0]["body"].lower()
    assert _conv(db_session, b).state == "collecting"


def test_button_edit_on_awaiting_confirm_keeps_partial_draft(db_session):
    """A mid-draft Edit (no invoice yet) must PRESERVE draft_payload so the
    owner can amend the in-progress invoice."""
    b = _biz(db_session)
    conv = _conv(db_session, b)
    conv.state = "awaiting_confirm"
    conv.draft_payload = {
        "customer_name": "Rajesh Traders",
        "line_items": [{"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}],
        "gaps": [],
    }
    db_session.flush()

    flow.handle_inbound(
        db_session, _payload(b, kind="button", button_id="wa_edit", text=None)
    )

    fresh = _conv(db_session, b)
    assert fresh.state == "collecting"
    assert fresh.draft_payload["customer_name"] == "Rajesh Traders"
    assert fresh.draft_payload["line_items"][0]["product_name"] == "Widget"


def test_unknown_button_treated_as_edit(db_session):
    b = _biz(db_session)
    conv = _conv(db_session, b)
    conv.state = "awaiting_confirm"

    out = flow.handle_inbound(
        db_session, _payload(b, kind="button", button_id="wa_bogus", text=None)
    )

    assert out[0]["kind"] == "text"
    assert _conv(db_session, b).state == "collecting"


def test_button_confirm_creates_invoice_via_handle_inbound(db_session):
    """The wa_confirm button branch runs handle_confirm end to end: an
    awaiting_confirm draft becomes exactly one invoice and a "created" reply."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _conv(db_session, b)
    conv.state = "awaiting_confirm"
    conv.draft_payload = {
        "customer_name": cust.name,
        "customer_id": str(cust.id),
        "line_items": [{"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}],
        "gaps": [],
    }
    db_session.flush()

    out = flow.handle_inbound(
        db_session, _payload(b, kind="button", button_id="wa_confirm", text=None)
    )

    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "created" in out[0]["body"].lower()
    assert out[0]["then_document_invoice_id"]
    assert db_session.query(Invoice).count() == 1
    fresh = _conv(db_session, b)
    assert fresh.state == "confirmed"
    assert fresh.invoice_id is not None


def test_button_confirm_wrong_state_reasks(db_session):
    """handle_confirm on a non-awaiting_confirm conv re-asks, creates nothing."""
    b = _biz(db_session)
    conv = _conv(db_session, b)
    conv.state = "collecting"

    out = flow.handle_confirm(db_session, conv, db_session.get(Business, b.id))

    assert len(out) == 1
    assert out[0]["kind"] == "buttons"
    assert db_session.query(Invoice).count() == 0


# --------------------------------------------------------------------------- #
# expiry
# --------------------------------------------------------------------------- #
def test_expired_awaiting_confirm_goes_terminal(db_session, monkeypatch):
    from datetime import datetime, timedelta

    b = _biz(db_session)
    conv = _conv(db_session, b)
    conv.state = "awaiting_confirm"
    conv.expires_at = datetime.utcnow() - timedelta(minutes=1)

    def _boom(*a, **k):
        raise AssertionError("parse_message must not be called for an expired draft")

    monkeypatch.setattr(flow, "parse_message", _boom)

    out = flow.handle_inbound(db_session, _payload(b))

    assert len(out) == 1
    assert "expired" in out[0]["body"].lower()
    assert _conv(db_session, b).state == "terminal"


def test_deleted_business_bails_before_parse(db_session, monkeypatch):
    import uuid as _uuid

    def _boom(*a, **k):
        raise AssertionError("parse_message must not run for a missing business")

    monkeypatch.setattr(flow, "parse_message", _boom)

    fake = type("B", (), {"id": _uuid.uuid4()})()
    out = flow.handle_inbound(db_session, _payload(fake))
    assert out == []


def test_terminal_conversation_resets_before_reparse(db_session, monkeypatch):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _conv(db_session, b)
    # simulate a prior draft that was abandoned/expired
    conv.draft_payload = {
        "customer_name": "Old Corp",
        "line_items": [{"product_name": "Old", "qty": "9", "price": "9", "gst_rate": "9"}],
        "gaps": [],
    }
    conv.state = "terminal"

    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders", line_items=[], gaps=["What are you invoicing?"]
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    flow.handle_inbound(db_session, _payload(b))

    fresh = _conv(db_session, b)
    assert fresh.state == "collecting"
    assert "Old" not in [li["product_name"] for li in fresh.draft_payload.get("line_items", [])]
    assert fresh.draft_payload.get("customer_name") == "Rajesh Traders"


def test_expired_collecting_starts_fresh(db_session, monkeypatch):
    """I1: a collecting conv past its 30-min TTL must start a clean draft -- the
    stale draft_payload must not merge into the new message, and must not be
    re-sent to Claude as prior_draft (spec: unusable for drafting 30 min after
    the last message)."""
    from datetime import datetime, timedelta

    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _conv(db_session, b)
    conv.draft_payload = {
        "customer_name": "Old Corp",
        "line_items": [{"product_name": "StaleItem", "qty": "9", "price": "9", "gst_rate": "9"}],
        "gaps": [],
    }
    conv.state = "collecting"
    conv.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db_session.flush()

    seen = {}

    def _parse(text, prior):
        seen["prior"] = prior
        return ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("FreshItem", Decimal("1"), Decimal("50"), Decimal("18"))],
            gaps=[],
        )

    monkeypatch.setattr(flow, "parse_message", _parse)
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))

    flow.handle_inbound(db_session, _payload(b))

    # the stale draft was wiped before parsing: prior_draft was empty
    assert seen["prior"] in (None, {})
    fresh = _conv(db_session, b)
    names = [li["product_name"] for li in fresh.draft_payload.get("line_items", [])]
    assert "StaleItem" not in names
    assert names == ["FreshItem"]
    assert fresh.draft_payload.get("customer_name") == "Rajesh Traders"
