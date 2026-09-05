"""Signed webhook router -- the entry point for every inbound WhatsApp event.

Wires together everything built in Phase A: signature verification
(``whatsapp_client``), connection resolution, message dedup, sender
authorization, rate limiting, and job enqueueing (``whatsapp_jobs``). This
router does no message *processing* -- it only decides whether a message is
safe/eligible to hand to the worker and, if so, enqueues a job. Phase B reads
the queue.

Deliberate spec deviation: an unauthorized sender gets logged and dropped,
never a reply. The spec's error table says "polite reply"; replying to an
arbitrary WhatsApp number is a spam-amplification / account-enumeration
vector (an attacker can probe numbers and learn which ones get a response),
and the legitimate path for enrolling a sender is the web app, not a bot
reply telling a stranger how to enroll. See task-A5 report for the full
rationale.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import rate_limit
from app.config import get_settings
from app.db import get_db
from app.models import WhatsAppAuthorizedSender, WhatsAppConnection, WhatsAppMessageLog
from app.rate_limit import count_in_window
from app.schemas.whatsapp import Message, WebhookPayload
from app.services import whatsapp_jobs
from app.services.whatsapp_client import verify_challenge, verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# Meta signs the raw body before we can trust it, so the buffer below is read
# before auth -- cap it. A real Meta webhook batch is a few KB.
_MAX_BODY_BYTES = 512_000
# A real Meta change carries a handful of messages; anything past this is abuse.
_MAX_MESSAGES_PER_CHANGE = 50
_TOO_LONG_REPLY = "That message is too long — please use the web app for this invoice."
_UNSUPPORTED_TYPE_REPLY = "I can only read typed invoice details."


def _mask_sender(sender: str) -> str:
    """Enough of a sender's E.164 number to correlate a support ticket without
    putting full phone numbers in logs."""
    if len(sender) <= 7:
        return "***"
    return sender[:3] + "***" + sender[-4:]


@router.get("/webhook")
def get_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    challenge = verify_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        return Response(status_code=403)
    return PlainTextResponse(challenge)


@router.post("/webhook")
async def post_webhook(request: Request, db: Session = Depends(get_db)):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                logger.warning("whatsapp webhook body over cap (content-length=%s)", content_length)
                return Response(status_code=413)
        except ValueError:
            pass  # unparseable header -- fall through; the body read is still bounded server-side

    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_webhook_signature(raw_body, signature):
        logger.warning("whatsapp webhook bad signature")
        return Response(status_code=403)

    try:
        payload = WebhookPayload.model_validate_json(raw_body)
    except ValidationError:
        logger.info("whatsapp webhook payload did not parse; acking anyway")
        return {"status": "ok"}

    for entry in payload.entry or []:
        for change in entry.changes or []:
            value = change.value
            if value is None:
                continue
            if not value.messages:
                # No messages (e.g. only `statuses` delivery receipts) --
                # nothing to do, ack and move on.
                continue

            phone_number_id = value.metadata.phone_number_id if value.metadata else None
            if not phone_number_id:
                continue

            # A partial unique index (`ux_whatsapp_connections_phone_number_id_active`)
            # enforces at most one active connection per phone_number_id at the DB
            # level. This is belt-and-suspenders for that invariant: use `.all()`
            # rather than `scalar_one_or_none()` so a violation (e.g. mid-migration-
            # rollout, or the constraint somehow bypassed) logs loudly and picks the
            # most-recent match deterministically, instead of crashing this public,
            # unauthenticated endpoint with `MultipleResultsFound`.
            candidates = (
                db.execute(
                    select(WhatsAppConnection)
                    .where(
                        WhatsAppConnection.phone_number_id == phone_number_id,
                        WhatsAppConnection.status == "active",
                    )
                    .order_by(WhatsAppConnection.created_at.desc())
                )
                .scalars()
                .all()
            )
            if len(candidates) > 1:
                logger.error(
                    "whatsapp webhook: %d active connections found for phone_number_id=%s "
                    "(expected at most 1) -- using the most recently created",
                    len(candidates),
                    phone_number_id,
                )
            connection = candidates[0] if candidates else None
            if connection is None:
                logger.info(
                    "whatsapp webhook: no active connection for phone_number_id=%s",
                    phone_number_id,
                )
                continue

            for message in value.messages[:_MAX_MESSAGES_PER_CHANGE]:
                _handle_message(db, connection, message)

    return {"status": "ok"}


def _handle_message(db: Session, connection: WhatsAppConnection, message: Message) -> None:
    """Decide whether one inbound message is eligible for the worker and, if so,
    enqueue its job. All the DB work for a message -- the dedup row, the job
    row, and the rate-limit event rows -- goes into ONE transaction with ONE
    commit, so a crash can never leave a dedup row committed without its job
    (which would silently drop the message on Meta's redelivery).
    """
    wa_message_id = message.id
    sender = message.from_
    if not wa_message_id or not sender:
        return

    business_id = connection.business_id

    # Authorization -- read-only, no writes.
    authorized = db.execute(
        select(WhatsAppAuthorizedSender).where(
            WhatsAppAuthorizedSender.business_id == business_id,
            WhatsAppAuthorizedSender.phone_e164 == sender,
        )
    ).scalar_one_or_none()
    if authorized is None:
        logger.info(
            "whatsapp webhook: unauthorized sender %s for business_id=%s, no reply sent",
            _mask_sender(sender),
            business_id,
        )
        db.rollback()
        return

    settings = get_settings()
    window = rate_limit.WHATSAPP_WINDOW_SECONDS
    business_bucket = f"wa:business:{business_id}"
    sender_bucket = f"wa:sender:{sender}"

    # Rate-limit CHECK -- read-only. Over cap => skip with no writes at all.
    if count_in_window(db, business_bucket, window) >= settings.whatsapp_rate_per_business:
        logger.info("whatsapp webhook: business %s rate-limited", business_id)
        db.rollback()
        return
    if count_in_window(db, sender_bucket, window) >= settings.whatsapp_rate_per_sender:
        logger.info("whatsapp webhook: sender %s rate-limited", _mask_sender(sender))
        db.rollback()
        return

    # Dedup insert -- no commit yet.
    if not _mark_seen(db, wa_message_id):
        logger.info("whatsapp webhook: duplicate wa_message_id=%s, skipping", wa_message_id)
        db.rollback()
        return

    job_spec = _job_for_message(message, business_id, sender, wa_message_id, settings)
    if job_spec is None:
        # Nothing worth handing the worker (e.g. an empty text body). The dedup
        # row still stands so Meta's redelivery is a no-op; commit just that.
        logger.info("whatsapp webhook: nothing to enqueue for wa_message_id=%s", wa_message_id)
        db.commit()
        return

    job_type, payload = job_spec
    whatsapp_jobs.build(db, job_type, payload, business_id=business_id)
    rate_limit.add_events(db, [business_bucket, sender_bucket])
    db.commit()


def _job_for_message(
    message: Message,
    business_id,
    sender: str,
    wa_message_id: str,
    settings,
) -> tuple[str, dict] | None:
    """Map an inbound message to the (job_type, payload) to enqueue, or None if
    the message is a no-op (empty text body -- a doomed parser call)."""
    msg_type = message.type
    if msg_type == "text":
        text_body = message.text.body if message.text else None
        text_body = text_body or ""
        if not text_body.strip():
            return None
        if len(text_body.encode("utf-8")) > settings.whatsapp_message_max_bytes:
            return "outbound_send", {
                "kind": "text",
                "to": sender,
                "business_id": str(business_id),
                "body": _TOO_LONG_REPLY,
            }
        return "inbound_message", {
            "business_id": str(business_id),
            "sender": sender,
            "wa_message_id": wa_message_id,
            "kind": "text",
            "text": text_body,
        }

    button_id = None
    if msg_type == "interactive" and message.interactive and message.interactive.button_reply:
        button_id = message.interactive.button_reply.id
    elif msg_type == "button" and message.button:
        button_id = message.button.payload

    if button_id is not None:
        return "inbound_message", {
            "business_id": str(business_id),
            "sender": sender,
            "wa_message_id": wa_message_id,
            "kind": "button",
            "button_id": button_id,
        }

    # Unsupported message type (image, audio, location, ...).
    return "outbound_send", {
        "kind": "text",
        "to": sender,
        "business_id": str(business_id),
        "body": _UNSUPPORTED_TYPE_REPLY,
    }


def _mark_seen(db: Session, wa_message_id: str) -> bool:
    """Insert the dedup row (no commit -- the caller owns the transaction).
    Returns True if this is the first time we've seen this wa_message_id (row
    inserted), False if it's a replay (conflict, no row inserted). Uses ON
    CONFLICT DO NOTHING rather than a plain INSERT so a replay never raises
    IntegrityError.

    Detects the outcome via ``RETURNING`` rather than ``result.rowcount``:
    with this project's psycopg driver, a fresh insert reports
    ``rowcount == 1`` but the conflict/no-op case reports ``rowcount == -1``
    instead of the ``0`` the brief's `result.rowcount == 0` check assumed --
    so rowcount alone can't reliably distinguish "inserted" from
    "conflicted" here. The presence of a returned row can.
    """
    stmt = (
        insert(WhatsAppMessageLog)
        .values(wa_message_id=wa_message_id, direction="in")
        .on_conflict_do_nothing(index_elements=["wa_message_id"])
        .returning(WhatsAppMessageLog.id)
    )
    row = db.execute(stmt).fetchone()
    return row is not None
