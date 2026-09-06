"""Decision logic for the WhatsApp -> invoice conversation (Task B4).

``handle_inbound`` is the heart of the worker's ``inbound_message`` handling: it
turns one inbound WhatsApp message (a text dictation or a button tap) into the
list of *outbound* reply payloads the worker should enqueue. It ties together
the parser (B1), the conversation store (B2), and the deterministic customer
lookup (B3).

**Pure of network.** This module never calls the Meta adapter. It returns
``outbound_send`` payload dicts and lets the worker enqueue them. Each payload
is::

    {"kind": "text",    "to": <sender e164>, "business_id": <str>, "body": <str>}
    {"kind": "buttons", "to": <sender e164>, "business_id": <str>, "body": <str>,
     "buttons": [("wa_confirm", "Confirm"), ("wa_edit", "Edit")]}

**Transaction contract.** Like the conversation store, this module never
commits. It mutates the row-locked ``WhatsAppConversation`` the worker handed in
(via ``get_locked``); the worker commits once the replies are enqueued, or rolls
back on error.

**Security.** The Claude parser only ever yields a free-text ``customer_name``;
the deterministic ``resolve`` (B3), scoped to the caller's business, decides
which ``customers`` row it maps to. An ``Ambiguous`` result is *always* a
question back to the owner, never an auto-pick. On the "ready for confirm"
branch we gate strictly on ``draft_payload["gaps"]`` being empty plus every line
carrying a positive qty/price and a GST rate -- never on an absence of
exceptions (``to_invoice_create`` does not raise on an empty draft).

``handle_confirm`` (the confirm -> invoice-create path) is Task B5; this module
ships a stub that raises ``NotImplementedError``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models import Business
from app.services import whatsapp_conversations as conv_store
from app.services.gst import LineItemInput, compute_invoice_totals
from app.services.invoice_ai_parser import parse_message
from app.services.whatsapp_customer_lookup import Ambiguous, Matched, NotFound, resolve

_EXPIRED_STATES = {"awaiting_confirm", "confirmed"}

_MSG_EDIT = "Okay — send the corrected details."
_MSG_EXPIRED = "That draft expired — start again with the full invoice details."
_MSG_NO_CUSTOMER = "Which customer is this invoice for?"


def _text(to: str, business_id, body: str) -> dict:
    return {"kind": "text", "to": to, "business_id": str(business_id), "body": body}


def _buttons(to: str, business_id, body: str) -> dict:
    return {
        "kind": "buttons",
        "to": to,
        "business_id": str(business_id),
        "body": body,
        "buttons": [("wa_confirm", "Confirm"), ("wa_edit", "Edit")],
    }


def handle_inbound(db: Session, job_payload: dict) -> list[dict]:
    """Process one inbound message, returning outbound reply payloads to enqueue.

    Raises ``ParserError`` (from ``parse_message``) straight through -- the
    worker converts that into a bounded retry.
    """
    business_id = uuid.UUID(str(job_payload["business_id"]))
    sender = job_payload["sender"]
    kind = job_payload.get("kind")

    business = db.get(Business, business_id)
    if business is None:
        # Business deleted between webhook enqueue and worker pickup. Bail before
        # parse_message so we don't burn (paid) Claude calls on every retry.
        return []

    conv = conv_store.get_locked(db, business_id, sender)

    # --- expiry: an aged-out draft that was awaiting confirmation (or frozen)
    # is dead; a fresh text starts over.
    if conv_store.is_expired(conv) and conv.state in _EXPIRED_STATES:
        conv.state = "terminal"
        return [_text(sender, business_id, _MSG_EXPIRED)]

    if kind == "button":
        return _handle_button(db, job_payload, conv, business, sender, business_id)

    if kind != "text":
        # Webhook only ever enqueues text / button inbound jobs; anything else
        # is a no-op reply-wise.
        return []

    return _handle_text(db, job_payload, conv, business, sender, business_id)


def _handle_button(db, job_payload, conv, business, sender, business_id) -> list[dict]:
    button_id = job_payload.get("button_id")
    if button_id == "wa_confirm":
        return handle_confirm(db, conv, business)
    # "wa_edit" or anything unrecognised -> back to collecting.
    conv.state = "collecting"
    return [_text(sender, business_id, _MSG_EDIT)]


def _handle_text(db, job_payload, conv, business, sender, business_id) -> list[dict]:
    text = job_payload["text"]

    # A finished conversation (invoice made, or expired/abandoned) starts fresh:
    # wipe the stale draft before parsing so merge_draft can't carry old
    # line_items into the new one. `confirmed` is left alone -- that transition
    # is B5's to own.
    # TODO(B5): decide reset behaviour for a `confirmed` conversation.
    if conv.state == "terminal":
        conv.draft_payload = {}
        conv.state = "collecting"

    draft = parse_message(text, conv.draft_payload)
    conv_store.merge_draft(conv, draft)
    conv_store.touch(conv)

    # A re-parse while awaiting confirmation drops back to collecting; only a
    # button tap advances the state machine forward.
    if conv.state == "awaiting_confirm":
        conv.state = "collecting"

    payload = conv.draft_payload or {}
    name = draft.customer_name or payload.get("customer_name")
    if not name or not str(name).strip():
        return [_text(sender, business_id, _MSG_NO_CUSTOMER)]

    match = resolve(db, business, name)
    if isinstance(match, NotFound):
        conv.state = "terminal"
        return [
            _text(
                sender,
                business_id,
                f"{name} isn't set up yet — add them on the web app, then resend.",
            )
        ]
    if isinstance(match, Ambiguous):
        listed = "; ".join(c.name for c in match.candidates)
        return [
            _text(
                sender,
                business_id,
                f"Which one? {listed} — resend with the exact name.",
            )
        ]

    assert isinstance(match, Matched)
    customer = match.customer

    # JSONB change detection: rebuild + reassign the whole dict (merge_draft
    # already reassigned once; setting a key in place afterwards would not be
    # seen by SQLAlchemy's non-mutable JSON type).
    payload = dict(conv.draft_payload or {})
    payload["customer_id"] = str(customer.id)
    conv.draft_payload = payload

    question = _first_gap_question(payload)
    if question is not None:
        return [_text(sender, business_id, question)]

    grand_total = _preview_grand_total(business, customer, payload)
    conv.state = "awaiting_confirm"
    body = (
        f"{customer.name}"
        + (f" (GSTIN {customer.gstin})" if customer.gstin else "")
        + f" — ₹{grand_total} incl. GST — confirm?"
    )
    return [_buttons(sender, business_id, body)]


def _dec(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _first_gap_question(payload: dict) -> str | None:
    """Return one targeted question for the first outstanding gap, or ``None``
    if the draft is ready for a confirm prompt.

    Ready == ``gaps`` empty AND >=1 line item AND every line has a positive
    qty/price and a non-null GST rate.
    """
    gaps = list(payload.get("gaps") or [])
    if gaps:
        return str(gaps[0])

    line_items = payload.get("line_items") or []
    if not line_items:
        return "What are you invoicing? Send the item, quantity and price."

    for li in line_items:
        name = li.get("product_name") or "that item"
        qty = _dec(li.get("qty"))
        price = _dec(li.get("price"))
        gst = _dec(li.get("gst_rate"))
        if qty is None or qty <= 0:
            return f"How many {name}?"
        if price is None or price <= 0:
            return f"What's the price for {name}?"
        if gst is None:
            return f"What's the GST rate for {name}?"

    return None


def _preview_grand_total(business, customer, payload: dict) -> Decimal:
    """Compute the preview grand total (no DB write), mirroring
    ``invoices.apply_totals_and_items``'s same-state comparison."""
    same_state = (
        bool(business.state)
        and bool(customer.place_of_supply)
        and business.state.strip().casefold() == customer.place_of_supply.strip().casefold()
    )
    items = [
        LineItemInput(
            qty=_dec(li.get("qty")) or Decimal("0"),
            price=_dec(li.get("price")) or Decimal("0"),
            discount=Decimal("0"),
            gst_rate=_dec(li.get("gst_rate")) or Decimal("0"),
        )
        for li in payload.get("line_items") or []
    ]
    discount_type = payload.get("discount_type") or "Rs"
    discount_value = _dec(payload.get("discount_value")) or Decimal("0")

    totals = compute_invoice_totals(
        items,
        same_state=same_state,
        discount_type=discount_type,
        discount_value=discount_value,
        tcs=Decimal("0"),
        round_off=True,
    )
    return totals.grand_total


def handle_confirm(db: Session, conv, business) -> list[dict]:
    """Confirm -> invoice-create path. Implemented in Task B5."""
    raise NotImplementedError("Task B5")
