"""Per-sender draft-conversation store for the WhatsApp -> invoice flow.

One row of ``whatsapp_conversations`` per ``(business_id, sender_phone_e164)``
holds the in-flight invoice draft a sender is dictating over one or more
WhatsApp messages, plus a small state machine:

    collecting        -> gathering slots; every inbound message re-parses and
                         merges into ``draft_payload``
    awaiting_confirm  -> draft looks complete; waiting for the sender to say yes
    confirmed         -> sender confirmed; the draft is frozen and an invoice
                         is being / has been created (``merge_draft`` is a
                         no-op from here so a late re-parse can't mutate it)
    terminal          -> conversation finished (invoice made, or abandoned /
                         expired); a fresh message starts a new one

Transaction contract: this module never commits. The worker owns the
transaction; it calls :func:`get_locked` to take a row lock for the duration of
one message's processing, mutates the returned object, and commits once.

``draft_payload`` is JSONB. SQLAlchemy's default (non-mutable) JSON type does
*not* detect in-place mutation of the dict, so :func:`merge_draft` and
:func:`to_invoice_create` always build a brand-new dict and reassign the whole
attribute.
"""

import uuid
from datetime import date, datetime, timedelta

from decimal import Decimal

from app.time_utils import utcnow

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import config
from app.models import WhatsAppConversation
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemInput
from app.services.invoice_ai_parser import ProposedDraft

STATES = frozenset({"collecting", "awaiting_confirm", "confirmed", "terminal"})


def _ttl() -> timedelta:
    return timedelta(minutes=config.get_settings().whatsapp_conversation_ttl_minutes)


def get_locked(
    db: Session, business_id: uuid.UUID, sender_e164: str
) -> WhatsAppConversation:
    """Return the ``(business_id, sender_e164)`` conversation row, locked
    ``FOR UPDATE`` in the caller's transaction, creating it if absent.

    The create path is race-safe: ``INSERT ... ON CONFLICT DO NOTHING`` (a
    concurrent inserter wins the unique index, our insert is a no-op) followed
    by an unconditional ``SELECT ... FOR UPDATE``, which always finds exactly
    one row and locks it. No commit -- the worker owns the transaction.
    """
    stmt = select(WhatsAppConversation).where(
        WhatsAppConversation.business_id == business_id,
        WhatsAppConversation.sender_phone_e164 == sender_e164,
    )

    row = db.execute(stmt.with_for_update()).scalar_one_or_none()
    if row is not None:
        return row

    db.execute(
        pg_insert(WhatsAppConversation)
        .values(
            business_id=business_id,
            sender_phone_e164=sender_e164,
            state="collecting",
            draft_payload={},
            expires_at=utcnow() + _ttl(),
        )
        .on_conflict_do_nothing(index_elements=["business_id", "sender_phone_e164"])
    )

    return db.execute(stmt.with_for_update()).scalar_one()


def is_expired(conv: WhatsAppConversation, now: datetime | None = None) -> bool:
    return (now or utcnow()) > conv.expires_at


def touch(conv: WhatsAppConversation) -> None:
    """Extend the TTL window (a fresh inbound message keeps the draft alive)."""
    conv.expires_at = utcnow() + _ttl()


def _line_items_to_json(proposed: ProposedDraft) -> list[dict]:
    return [
        {
            "product_name": li.product_name,
            "qty": str(li.qty),
            "price": str(li.price),
            "gst_rate": str(li.gst_rate),
        }
        for li in proposed.line_items
    ]


def merge_draft(conv: WhatsAppConversation, proposed: ProposedDraft) -> None:
    """Slot-fill merge of one parse into ``conv.draft_payload``.

    New non-null info wins per field; a parse that names >=1 line item replaces
    the line-item list wholesale, otherwise the prior list is kept. ``gaps`` is
    always overwritten with the latest parse's view. A ``confirmed`` draft is
    frozen -- this is a no-op.
    """
    if conv.state == "confirmed":
        return

    payload = dict(conv.draft_payload or {})

    if proposed.customer_name is not None:
        payload["customer_name"] = proposed.customer_name

    if len(proposed.line_items) >= 1:
        payload["line_items"] = _line_items_to_json(proposed)

    if proposed.discount_type is not None:
        payload["discount_type"] = proposed.discount_type
    if proposed.discount_value is not None:
        payload["discount_value"] = str(proposed.discount_value)
    if proposed.notes is not None:
        payload["notes"] = proposed.notes

    payload["gaps"] = list(proposed.gaps)

    conv.draft_payload = payload


def to_invoice_create(
    conv: WhatsAppConversation, customer_id: uuid.UUID
) -> InvoiceCreate:
    """Build the web-form ``InvoiceCreate`` payload from the stored draft.

    Decimals were stored as strings; convert them back.

    The caller (the worker) MUST gate on ``conv.draft_payload["gaps"]`` being
    empty and at least one line item present before calling this. As a
    defense-in-depth backstop, ``InvoiceCreate`` now enforces
    ``line_items`` min length 1 and bounds every numeric field, so a
    malformed / empty draft raises ``pydantic.ValidationError`` here rather
    than producing a bad invoice downstream.
    """
    payload = conv.draft_payload or {}

    line_items = [
        InvoiceLineItemInput(
            product_name=li["product_name"],
            qty=Decimal(str(li["qty"])),
            price=Decimal(str(li["price"])),
            gst_rate=Decimal(str(li.get("gst_rate", "0"))),
        )
        for li in payload.get("line_items", [])
    ]

    kwargs: dict = {
        "customer_id": customer_id,
        "invoice_date": date.today(),
        "line_items": line_items,
    }
    if payload.get("discount_type") is not None:
        kwargs["discount_type"] = payload["discount_type"]
    if payload.get("discount_value") is not None:
        kwargs["discount_value"] = Decimal(str(payload["discount_value"]))
    if payload.get("notes") is not None:
        kwargs["notes"] = payload["notes"]

    return InvoiceCreate(**kwargs)
