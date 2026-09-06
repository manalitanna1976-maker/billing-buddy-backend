"""Task B5: whatsapp_flow.handle_confirm -- the idempotent confirm -> invoice
create transition.

handle_confirm makes its OWN commits (unlike the rest of whatsapp_flow); the
commit-before-create ordering is the idempotency mechanism. These tests pin
that behaviour: exactly one invoice per draft, a double tap re-sends the stored
result, and a concurrent worker that is mid-create is a no-op.
"""

from decimal import Decimal

import pytest

from app.models import Business, Customer, Invoice
from app.services import whatsapp_conversations as cs
from app.services import whatsapp_flow as flow
from app.services.invoice_ai_parser import ProposedDraft, ProposedLine
from app.services.invoices import CustomerNotFoundError
from app.services.whatsapp_customer_lookup import Matched


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


def _awaiting_conv(db, business, customer, sender="+919000000001"):
    conv = cs.get_locked(db, business.id, sender)
    conv.state = "awaiting_confirm"
    conv.draft_payload = {
        "customer_name": customer.name,
        "customer_id": str(customer.id),
        "line_items": [
            {"product_name": "Widget", "qty": "2", "price": "100", "gst_rate": "18"}
        ],
        "gaps": [],
    }
    db.flush()
    return conv


def test_confirm_creates_exactly_one_invoice(db_session):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)

    out = flow.handle_confirm(db_session, conv, b)

    invoices = db_session.query(Invoice).all()
    assert len(invoices) == 1
    inv = invoices[0]
    assert inv.invoice_no == "1"
    assert inv.customer_id == cust.id
    assert len(inv.line_items) == 1
    li = inv.line_items[0]
    assert li.product_name == "Widget"
    assert li.qty == Decimal("2")
    assert li.price == Decimal("100")
    assert li.gst_rate == Decimal("18")

    assert conv.state == "confirmed"
    assert conv.invoice_id == inv.id
    assert conv.last_result_payload["kind"] == "text"
    assert conv.last_result_payload["body"] == "Invoice 1 created."
    assert conv.last_result_payload["then_document_invoice_id"] == str(inv.id)
    assert out == [conv.last_result_payload]


def test_double_confirm_is_idempotent(db_session):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)

    first = flow.handle_confirm(db_session, conv, b)
    second = flow.handle_confirm(db_session, conv, b)

    assert db_session.query(Invoice).count() == 1
    assert second == [conv.last_result_payload]
    assert second == first


def test_confirm_mid_create_concurrent_returns_empty(db_session):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)
    # A concurrent worker committed state="confirmed" (step 3c) but has not yet
    # committed the invoice (step 3e): invoice_id is still None.
    conv.state = "confirmed"
    conv.invoice_id = None
    db_session.flush()

    out = flow.handle_confirm(db_session, conv, b)

    assert out == []
    assert db_session.query(Invoice).count() == 0


def test_confirm_customer_deleted_since_awaiting(db_session):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)
    db_session.delete(cust)
    db_session.flush()

    out = flow.handle_confirm(db_session, conv, b)

    assert db_session.query(Invoice).count() == 0
    assert conv.state == "terminal"
    assert len(out) == 1
    assert out[0]["kind"] == "text"
    assert "removed" in out[0]["body"].lower()


def test_confirm_uses_shared_numbering(db_session):
    b = _biz(db_session)
    c1 = _cust(db_session, b, name="Rajesh Traders")
    c2 = _cust(db_session, b, name="Suresh Traders")
    conv1 = _awaiting_conv(db_session, b, c1, sender="+919000000001")
    conv2 = _awaiting_conv(db_session, b, c2, sender="+919000000002")

    flow.handle_confirm(db_session, conv1, b)
    flow.handle_confirm(db_session, conv2, b)

    nos = sorted(i.invoice_no for i in db_session.query(Invoice).all())
    assert nos == ["1", "2"]


def test_confirm_wrong_state_reasks(db_session):
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)
    conv.state = "collecting"
    db_session.flush()

    out = flow.handle_confirm(db_session, conv, b)

    assert db_session.query(Invoice).count() == 0
    assert len(out) == 1
    assert out[0]["kind"] == "buttons"
    assert out[0]["buttons"] == [("wa_confirm", "Confirm"), ("wa_edit", "Edit")]
    assert conv.state == "collecting"


def test_confirm_after_invoice_exists_never_creates_second(db_session):
    """C2: invoice_id being set is the authoritative 'done' latch. Even if the
    conversation is somehow re-armed to awaiting_confirm, a Confirm tap re-sends
    the stored result and never mints a second invoice."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)

    first = flow.handle_confirm(db_session, conv, b)

    # Simulate a follow-up text that (buggily or otherwise) re-armed the state.
    conv.state = "awaiting_confirm"
    db_session.flush()

    second = flow.handle_confirm(db_session, conv, b)

    assert db_session.query(Invoice).count() == 1
    assert second == first == [conv.last_result_payload]


def test_confirm_then_text_then_confirm_is_one_invoice(db_session, monkeypatch):
    """C2 end-to-end through handle_inbound: confirm -> a chatty follow-up text
    -> Confirm again => still exactly one invoice."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    _awaiting_conv(db_session, b, cust)

    def _payload(**extra):
        p = {
            "business_id": str(b.id),
            "sender": "+919000000001",
            "wa_message_id": "wamid.x",
            "kind": "button",
            "button_id": "wa_confirm",
            "text": None,
        }
        p.update(extra)
        return p

    out1 = flow.handle_inbound(db_session, _payload())
    assert "created" in out1[0]["body"].lower()
    assert db_session.query(Invoice).count() == 1

    # a post-confirm "ok thanks" -- parser yields nothing actionable
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name=None, line_items=[], gaps=["What are you invoicing?"]
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("resolve must not run for a chatty follow-up")
    ))
    flow.handle_inbound(db_session, _payload(kind="text", button_id=None, text="ok thanks"))

    conv = cs.get_locked(db_session, b.id, "+919000000001")
    assert conv.state == "collecting"
    assert conv.draft_payload.get("line_items") in (None, [])
    # the fresh-draft reset also cleared the previous invoice's result
    assert conv.invoice_id is None
    assert conv.last_result_payload is None

    # a stale Confirm tap on this now-empty draft is a harmless "not ready" re-ask
    out3 = flow.handle_inbound(db_session, _payload())
    assert db_session.query(Invoice).count() == 1
    assert len(out3) == 1
    assert out3[0]["kind"] == "buttons"
    assert "ready to confirm" in out3[0]["body"].lower()


def test_same_sender_second_invoice_after_first(db_session, monkeypatch):
    """The (business, sender) conv is reusable: after confirming invoice #1, a
    fresh full dictation + Confirm makes invoice #2 -- invoice_id is not a
    permanent latch once the fresh-draft reset clears it."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    _awaiting_conv(db_session, b, cust)

    def _payload(**extra):
        p = {
            "business_id": str(b.id),
            "sender": "+919000000001",
            "wa_message_id": "wamid.x",
            "kind": "button",
            "button_id": "wa_confirm",
            "text": None,
        }
        p.update(extra)
        return p

    out1 = flow.handle_inbound(db_session, _payload())
    assert "Invoice 1 created." == out1[0]["body"]
    inv1_id = cs.get_locked(db_session, b.id, "+919000000001").invoice_id

    # 35 min later the sender dictates a complete second invoice (different item)
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("Gadget", Decimal("3"), Decimal("50"), Decimal("18"))],
            gaps=[],
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda *a, **k: Matched(customer=cust))
    out2 = flow.handle_inbound(
        db_session, _payload(kind="text", button_id=None, text="invoice rajesh 3 gadgets at 50")
    )
    assert out2[0]["kind"] == "buttons"  # awaiting_confirm

    out3 = flow.handle_inbound(db_session, _payload())

    assert db_session.query(Invoice).count() == 2
    nos = sorted(i.invoice_no for i in db_session.query(Invoice).all())
    assert nos == ["1", "2"]
    conv = cs.get_locked(db_session, b.id, "+919000000001")
    assert conv.invoice_id != inv1_id
    inv2 = db_session.get(Invoice, conv.invoice_id)
    assert inv2.invoice_no == "2"
    assert out3[0]["body"] == "Invoice 2 created."
    assert out3[0]["then_document_invoice_id"] == str(inv2.id)


def test_edit_tap_after_invoice_then_redictate_makes_second_invoice(db_session, monkeypatch):
    """A stale Edit tap on a confirmed conv (invoice_id set) means 'start over':
    it clears the latch, so a fresh dictation + Confirm mints invoice #2."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    _awaiting_conv(db_session, b, cust)

    def _payload(**extra):
        p = {
            "business_id": str(b.id),
            "sender": "+919000000001",
            "wa_message_id": "wamid.x",
            "kind": "button",
            "button_id": "wa_confirm",
            "text": None,
        }
        p.update(extra)
        return p

    flow.handle_inbound(db_session, _payload())  # confirm #1
    inv1_id = cs.get_locked(db_session, b.id, "+919000000001").invoice_id
    assert inv1_id is not None

    # stale Edit tap while the confirmed conv is still inside its TTL
    flow.handle_inbound(db_session, _payload(button_id="wa_edit"))
    conv = cs.get_locked(db_session, b.id, "+919000000001")
    assert conv.state == "collecting"
    assert conv.invoice_id is None
    assert conv.draft_payload == {}

    # a complete fresh dictation, then Confirm
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("Gizmo", Decimal("1"), Decimal("400"), Decimal("18"))],
            gaps=[],
        ),
    )
    monkeypatch.setattr(flow, "resolve", lambda *a, **k: Matched(customer=cust))
    flow.handle_inbound(db_session, _payload(kind="text", button_id=None, text="rajesh 1 gizmo 400"))
    out = flow.handle_inbound(db_session, _payload())

    assert db_session.query(Invoice).count() == 2
    conv = cs.get_locked(db_session, b.id, "+919000000001")
    assert conv.invoice_id != inv1_id
    inv2 = db_session.get(Invoice, conv.invoice_id)
    assert inv2.invoice_no == "2"
    assert out[0]["body"] == "Invoice 2 created."


def test_confirm_customer_not_found_during_create_is_terminal(db_session, monkeypatch):
    """M1: create_invoice_for_business raising CustomerNotFoundError (race: the
    customer was deleted after the re-fetch) -> terminal, zero invoices, and a
    re-run is a no-op (not re-enterable)."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)

    def _boom(db, business, body):
        raise CustomerNotFoundError("Customer not found")

    monkeypatch.setattr(flow, "create_invoice_for_business", _boom)

    out = flow.handle_confirm(db_session, conv, b)

    assert db_session.query(Invoice).count() == 0
    assert conv.state == "terminal"
    assert out == [conv.last_result_payload]
    assert "web app" in out[0]["body"].lower()

    # re-run: not re-enterable into the create path -- no invoice, no second
    # create attempt (terminal state -> a harmless re-ask, never a "created").
    monkeypatch.undo()
    again = flow.handle_confirm(db_session, conv, b)
    assert db_session.query(Invoice).count() == 0
    assert "created" not in again[0]["body"].lower()


def test_confirm_atomic_no_orphan_invoice_on_commit_failure(db_session, monkeypatch):
    """C1: if the commit that persists the invoice + conv.invoice_id fails, the
    invoice must NOT be committed (no orphan invoice with conv.invoice_id None).
    Single commit => atomic."""
    b = _biz(db_session)
    cust = _cust(db_session, b)
    conv = _awaiting_conv(db_session, b, cust)

    real_create = flow.create_invoice_for_business

    def _create_then_break_commit(db, business, body):
        inv = real_create(db, business, body)

        def _fail():
            raise RuntimeError("connection dropped on commit")

        monkeypatch.setattr(db, "commit", _fail)
        return inv

    monkeypatch.setattr(flow, "create_invoice_for_business", _create_then_break_commit)

    with pytest.raises(RuntimeError):
        flow.handle_confirm(db_session, conv, b)

    monkeypatch.undo()
    db_session.rollback()

    # No orphan: either nothing was committed, or (would-be) invoice_id is set.
    # With a single commit it's the former.
    assert db_session.query(Invoice).count() == 0
    conv = cs.get_locked(db_session, b.id, "+919000000001")
    assert conv.invoice_id is None
