"""Task B6: the ``outbound_send`` job handler -- the real Meta adapter call.

``whatsapp_flow`` is pure of network: it only ever *returns* outbound payload
dicts, which the worker enqueues as ``outbound_send`` jobs. THIS module is where
those payloads actually hit the Meta Cloud API.

Contract:

* ``handle_outbound(db, job)`` loads the business's *active*
  ``WhatsAppConnection``, decrypts its token, and dispatches on
  ``job.payload["kind"]`` (``text`` / ``buttons`` / ``document``).
* On a successful send it records ONE ``whatsapp_message_log`` row
  (``direction="out"``, **never a body**) with ``ON CONFLICT DO NOTHING`` on
  ``wa_message_id``, builds any follow-up ``document`` job, marks the job
  ``done``, and commits ALL of that in ONE transaction (the B4 precedent) -- so
  a crash cannot leave the job re-claimable after a successful send and thereby
  double the Meta message / follow-up job / log row.
* A ``text`` payload carrying ``then_document_invoice_id`` enqueues a follow-up
  ``document`` job in that same transaction, so the PDF send can never be
  silently lost after the text commit.
* ``WhatsAppSendError`` / ``RuntimeError`` propagate: the worker's ``run_once``
  try/except hands them to ``whatsapp_jobs.fail`` -> bounded retry ->
  dead-letter. This retry is independent of invoice creation (the invoice is
  already committed by ``handle_confirm`` before the send job exists).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Invoice, WhatsAppConnection, WhatsAppJob, WhatsAppMessageLog
from app.security_crypto import decrypt_secret
from app.services import pdf
from app.services import whatsapp_client
from app.services import whatsapp_jobs as jobs
from app.services.whatsapp_client import OutboundConn

logger = logging.getLogger(__name__)


def handle_outbound(db: Session, job: WhatsAppJob) -> None:
    payload = job.payload
    business_id = uuid.UUID(str(payload["business_id"]))

    # A partial unique index enforces at most one active connection per
    # phone_number_id, but `.first()` is defensive against a constraint bypass.
    wac = (
        db.execute(
            select(WhatsAppConnection).where(
                WhatsAppConnection.business_id == business_id,
                WhatsAppConnection.status == "active",
            )
        )
        .scalars()
        .first()
    )
    if wac is None:
        # -> job fails -> retries -> dead-letter. The owner's PDF is stranded
        # but the invoice is safe (already committed). Spec-acceptable.
        raise RuntimeError("no active connection")

    conn = OutboundConn(wac.phone_number_id, decrypt_secret(wac.access_token_encrypted))
    kind = payload["kind"]
    to = payload["to"]

    if kind == "text":
        mid = whatsapp_client.send_text(conn, to, payload["body"])
    elif kind == "buttons":
        # JSONB round-trips tuples as lists; the adapter wants [(id, title)].
        buttons = [tuple(b) for b in payload["buttons"]]
        mid = whatsapp_client.send_buttons(conn, to, payload["body"], buttons)
    elif kind == "document":
        inv = db.get(Invoice, uuid.UUID(str(payload["invoice_id"])))
        # Tenant check: the connection is business-scoped but the invoice is
        # fetched by PK -- this is the one place a full customer invoice PDF is
        # rendered and sent to a phone number (I6). Same message either way so
        # existence is not leaked.
        if inv is None or inv.business_id != business_id:
            raise RuntimeError("invoice not found for document send")
        pdf_bytes = pdf.render_invoice_pdf(inv)
        filename = f"{inv.invoice_no}.pdf"
        media_id = whatsapp_client.upload_media(
            conn, pdf_bytes, filename, "application/pdf"
        )
        caption = payload.get("caption") or f"Invoice {inv.invoice_no}"
        mid = whatsapp_client.send_document(
            conn, to, media_id, filename, caption=caption
        )
    else:
        raise RuntimeError(f"unknown outbound kind {kind!r}")

    # NOTE(Phase C): a crash between the Meta HTTP response above and the single
    # commit below stale-reclaims the job and re-sends ONE duplicate message.
    # Closing that residual window needs status-webhook reconciliation (an
    # idempotency key echoed back on the delivery receipt). Everything from here
    # down -- the log row, the follow-up job, job.status="done" -- commits
    # atomically, so a re-claim never *compounds* (no second follow-up job, no
    # orphan log row).
    db.execute(
        pg_insert(WhatsAppMessageLog)
        .values(wa_message_id=mid, direction="out")
        .on_conflict_do_nothing(index_elements=["wa_message_id"])
    )

    then_doc = payload.get("then_document_invoice_id")
    if then_doc:
        # `build` (no commit) folds the follow-up into the same transaction.
        jobs.build(
            db,
            "outbound_send",
            {
                "kind": "document",
                "to": to,
                "business_id": str(business_id),
                "invoice_id": str(then_doc),
            },
            business_id=business_id,
        )

    job.status = "done"
    job.processed_at = datetime.utcnow()
    db.commit()
    logger.info(
        "whatsapp outbound sent kind=%s business=%s wa_message_id=%s",
        kind,
        business_id,
        mid,
    )
