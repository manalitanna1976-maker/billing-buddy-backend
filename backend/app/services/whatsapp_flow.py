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

``handle_confirm`` (the confirm -> invoice-create path, Task B5) is the one
exception to the "never commits" contract: it makes its own commits in a
deliberate order so the confirm transition is *idempotent by construction* --
see its docstring.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models import Business, Customer
from app.services import whatsapp_conversations as conv_store
from app.services.gst import LineItemInput, compute_invoice_totals
from app.services.invoice_ai_parser import parse_message
from app.services.invoices import CustomerNotFoundError, create_invoice_for_business
from app.services.whatsapp_customer_lookup import Ambiguous, Matched, NotFound, resolve

logger = logging.getLogger(__name__)

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
    # is dead; a fresh text starts over. An invoice that exists (invoice_id set)
    # is NEVER "expired" -- it must still reach handle_confirm's idempotent
    # re-send (case 1) so the PDF is not lost (I4).
    if conv.invoice_id is None and conv_store.is_expired(conv):
        if conv.state in _EXPIRED_STATES:
            conv.state = "terminal"
            return [_text(sender, business_id, _MSG_EXPIRED)]
        # Past the 30-min TTL in any other non-terminal state (collecting): a
        # fresh text starts a clean draft, never resumes the stale one -- spec
        # §Retention: "unusable for drafting 30 minutes after the last message"
        # (I1). Without this the day-old draft_payload merges into the new
        # message and stale PII is re-sent to Claude as prior_draft.
        _reset_to_fresh_draft(conv)

    if kind == "button":
        return _handle_button(db, job_payload, conv, business, sender, business_id)

    if kind != "text":
        # Webhook only ever enqueues text / button inbound jobs; anything else
        # is a no-op reply-wise.
        return []

    return _handle_text(db, job_payload, conv, business, sender, business_id)


def _reset_to_fresh_draft(conv) -> None:
    """Wipe a finished conversation back to an empty ``collecting`` draft.

    Clearing ``invoice_id`` / ``last_result_payload`` is essential, not
    cosmetic: ``handle_confirm``'s first check treats a set ``invoice_id`` as a
    permanent "already done" latch. Leaving it set on any path that starts a new
    draft would block this ``(business, sender)`` from ever creating a second
    invoice and make the next Confirm re-send the *first* invoice's stale
    payload / PDF.
    """
    conv.draft_payload = {}
    conv.state = "collecting"
    conv.invoice_id = None
    conv.last_result_payload = None


def _handle_button(db, job_payload, conv, business, sender, business_id) -> list[dict]:
    button_id = job_payload.get("button_id")
    if button_id == "wa_confirm":
        return handle_confirm(db, conv, business)
    # "wa_edit" or anything unrecognised -> back to collecting.
    if conv.invoice_id is not None:
        # An Edit tap after an invoice was already created (a stale button on a
        # confirmed conv, possibly still inside its TTL) means "start over" --
        # clear the latch so the next dictation can confirm a fresh invoice.
        _reset_to_fresh_draft(conv)
    else:
        # A mid-draft Edit on an awaiting_confirm conv: KEEP the partial draft so
        # the owner can amend it -- that's the point of Edit.
        conv.state = "collecting"
    return [_text(sender, business_id, _MSG_EDIT)]


def _handle_text(db, job_payload, conv, business, sender, business_id) -> list[dict]:
    text = job_payload["text"]

    # A finished conversation starts fresh: wipe the stale draft AND the
    # previous invoice's result before parsing. The `invoice_id is not None`
    # latch is the authoritative trigger (not `state`): the confirm split-window
    # race can leave `state="collecting"` WITH `invoice_id` set -- a combination
    # no state-only reset covers, which otherwise re-sends invoice #1 forever
    # (I2). `terminal` / `confirmed` are also covered: a post-confirm follow-up
    # text ("ok thanks") must begin a genuinely new draft, never re-arm the
    # frozen one.
    if conv.invoice_id is not None or conv.state in ("terminal", "confirmed"):
        _reset_to_fresh_draft(conv)

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

    Ready == ``gaps`` empty AND >=1 line item AND every line has a non-empty
    product name, a positive qty/price and a non-null GST rate.
    """
    gaps = list(payload.get("gaps") or [])
    if gaps:
        return str(gaps[0])

    line_items = payload.get("line_items") or []
    if not line_items:
        return "What are you invoicing? Send the item, quantity and price."

    for li in line_items:
        raw_name = li.get("product_name")
        if raw_name is None or not str(raw_name).strip():
            return "What are you invoicing? Send the item, quantity and price."
        name = raw_name
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
    """Owner tapped *Confirm* -> create the invoice. Idempotent by construction.

    Unlike the rest of this module (which never commits), ``handle_confirm``
    makes its OWN commits in a deliberate sequence -- that sequence *is* the
    idempotency mechanism:

    1. ``conv.invoice_id is not None`` -> the invoice already exists. Idempotent
       re-send: return the stored ``last_result_payload`` (or ``[]`` if somehow
       unset). This is checked FIRST, regardless of ``state`` -- ``invoice_id``
       being set is the authoritative "already done" signal, so a re-armed
       conversation can never mint a second invoice.
    2. ``state == "confirmed"`` with ``invoice_id`` still None -> a concurrent
       worker committed the state transition (step 3c) but has not yet
       committed the invoice. Do nothing and return ``[]``; that worker will
       send the result.
    3. ``state`` is neither of the above and not ``awaiting_confirm`` (e.g.
       ``collecting`` / ``terminal``) -> a buttons re-ask.
    4. ``state == "awaiting_confirm"`` (the real path):
       a. re-fetch the customer; gone / not ours -> ``terminal`` + commit.
       b. build the ``InvoiceCreate`` from the frozen draft.
       c. ``state = "confirmed"``; **commit before creating** so a crash
          mid-create (or a concurrent second Confirm) lands in case 2 and
          does nothing.
       d. create the invoice (flush, no commit), set ``invoice_id`` +
          ``last_result_payload``, then ONE commit -- the invoice row and the
          conversation fields land atomically. A failure anywhere before that
          commit leaves NO invoice and NO ``invoice_id``: no orphan state.
       e. return ``[last_result_payload]``.

    ``run_once``'s trailing commit then only persists ``job.status="done"``. A
    crash after step 4d's commit but before that -> the inbound job is
    stale-reclaimed, ``handle_confirm`` re-runs, hits case 1 (``invoice_id``
    set) and re-returns the payload. Idempotent.
    """
    sender = conv.sender_phone_e164
    business_id = business.id

    # --- case 1: the invoice already exists -> idempotent re-send ----------- #
    # invoice_id is the authoritative "done" flag, checked before state so a
    # conversation that was somehow re-armed to awaiting_confirm still can't
    # create a second invoice.
    if conv.invoice_id is not None:
        return [conv.last_result_payload] if conv.last_result_payload else []

    # --- case 1b: a create attempt already failed for good ----------------- #
    # `state="terminal"` WITH a stored result payload but no invoice_id means a
    # previous create raised (case 4 below drove it here). Re-send that verdict
    # so a re-claimed confirm job is idempotent, never `[]` and never a generic
    # "not ready" re-ask (I3).
    if conv.state == "terminal" and conv.last_result_payload:
        return [conv.last_result_payload]

    # --- case 2: a concurrent worker is mid-create, OR it died mid-create -- #
    # It committed state="confirmed" (step 4c) but hasn't committed the invoice.
    # If the row is fresh, a live worker still owns it -> do nothing. If it has
    # been stranded past the 15-min cutoff (same one the retention sweep uses),
    # the create was lost: drive it terminal with a failure reply so the confirm
    # is never silently dropped (I3).
    if conv.state == "confirmed":
        stale_cutoff = datetime.utcnow() - timedelta(minutes=15)
        if conv.updated_at is not None and conv.updated_at < stale_cutoff:
            conv.state = "terminal"
            conv.last_result_payload = _text(
                sender,
                business_id,
                "Couldn't create that invoice — please use the web app.",
            )
            db.commit()
            return [conv.last_result_payload]
        return []

    # --- case 3: not ready to confirm ------------------------------------- #
    if conv.state != "awaiting_confirm":
        return [
            _buttons(
                sender,
                business_id,
                "That draft isn't ready to confirm — send the invoice details again.",
            )
        ]

    # --- case 4: the real path ------------------------------------------- #
    customer_id = uuid.UUID(conv.draft_payload["customer_id"])
    cust = db.get(Customer, customer_id)
    if cust is None or cust.business_id != business.id:
        conv.state = "terminal"
        db.commit()
        return [
            _text(
                sender,
                business_id,
                "That customer was removed — add them again on the web app and start over.",
            )
        ]

    body = conv_store.to_invoice_create(conv, customer_id)

    # Commit the state transition BEFORE creating. Now a crash mid-create, or a
    # concurrent second Confirm, sees confirmed + invoice_id is None (case 2).
    conv.state = "confirmed"
    db.commit()

    try:
        invoice = create_invoice_for_business(db, business, body)
        # create_invoice_for_business already flush()ed: Invoice.id (uuid
        # default) and .invoice_no (computed in Python by numbering.py) are both
        # populated now. Set the conversation fields and commit ONCE so the
        # invoice row + conv.invoice_id + conv.last_result_payload land
        # atomically -- a failure before this commit leaves no orphan invoice.
        conv.invoice_id = invoice.id
        conv.last_result_payload = {
            "kind": "text",
            "to": conv.sender_phone_e164,
            "business_id": str(business.id),
            "body": f"Invoice {invoice.invoice_no} created.",
            "then_document_invoice_id": str(invoice.id),
        }
        db.commit()
    except CustomerNotFoundError:
        # Shouldn't happen after the re-fetch above, but be safe: the state is
        # already "confirmed" from the commit above, so we must not leave the
        # conversation re-enterable -- drive it terminal with a result payload.
        db.rollback()
        conv.state = "terminal"
        conv.last_result_payload = _text(
            sender,
            business_id,
            "Couldn't create the invoice — please use the web app.",
        )
        db.commit()
        return [conv.last_result_payload]
    except Exception:
        # Any other create/commit failure (OperationalError, serialization
        # failure, IntegrityError, ...): state is already "confirmed", so the
        # conversation must not stay re-enterable and silently drop the confirm
        # (I3). Drive it terminal with a result payload -- the owner is told,
        # the job completes, nothing is re-raised. Log at exception level so a
        # genuine create bug is visible to ops, not just "use the web app".
        logger.exception(
            "whatsapp confirm: invoice create failed for business=%s sender=%s",
            business_id,
            sender,
        )
        db.rollback()
        conv.state = "terminal"
        conv.last_result_payload = _text(
            sender,
            business_id,
            "Couldn't create that invoice — please use the web app.",
        )
        db.commit()
        return [conv.last_result_payload]

    return [conv.last_result_payload]
