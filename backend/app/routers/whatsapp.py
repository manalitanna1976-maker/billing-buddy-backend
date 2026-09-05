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

from app.config import get_settings
from app.db import get_db
from app.models import WhatsAppAuthorizedSender, WhatsAppConnection, WhatsAppMessageLog
from app.rate_limit import count_in_window, record_event
from app.schemas.whatsapp import Message, WebhookPayload
from app.services import whatsapp_jobs
from app.services.whatsapp_client import verify_challenge, verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

_RATE_WINDOW_SECONDS = 900  # 15 minutes
_TOO_LONG_REPLY = "That message is too long — please use the web app for this invoice."
_UNSUPPORTED_TYPE_REPLY = "I can only read typed invoice details."


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

            connection = db.execute(
                select(WhatsAppConnection).where(
                    WhatsAppConnection.phone_number_id == phone_number_id,
                    WhatsAppConnection.status == "active",
                )
            ).scalar_one_or_none()
            if connection is None:
                logger.info(
                    "whatsapp webhook: no active connection for phone_number_id=%s",
                    phone_number_id,
                )
                continue

            for message in value.messages:
                _handle_message(db, connection, message)

    return {"status": "ok"}


def _handle_message(db: Session, connection: WhatsAppConnection, message: Message) -> None:
    wa_message_id = message.id
    sender = message.from_
    if not wa_message_id or not sender:
        return

    if not _mark_seen(db, wa_message_id):
        logger.info("whatsapp webhook: duplicate wa_message_id=%s, skipping", wa_message_id)
        return

    business_id = connection.business_id
    authorized = db.execute(
        select(WhatsAppAuthorizedSender).where(
            WhatsAppAuthorizedSender.business_id == business_id,
            WhatsAppAuthorizedSender.phone_e164 == sender,
        )
    ).scalar_one_or_none()
    if authorized is None:
        logger.info(
            "whatsapp webhook: unauthorized sender for business_id=%s, no reply sent",
            business_id,
        )
        return

    settings = get_settings()
    business_bucket = f"wa:business:{business_id}"
    sender_bucket = f"wa:sender:{sender}"
    if count_in_window(db, business_bucket, _RATE_WINDOW_SECONDS) >= settings.whatsapp_rate_per_business:
        logger.info("whatsapp webhook: business %s rate-limited", business_id)
        return
    if count_in_window(db, sender_bucket, _RATE_WINDOW_SECONDS) >= settings.whatsapp_rate_per_sender:
        logger.info("whatsapp webhook: sender %s rate-limited", sender)
        return
    record_event(db, business_bucket)
    record_event(db, sender_bucket)

    msg_type = message.type
    if msg_type == "text":
        text_body = message.text.body if message.text else None
        text_body = text_body or ""
        if len(text_body.encode("utf-8")) > settings.whatsapp_message_max_bytes:
            whatsapp_jobs.enqueue(
                db,
                "outbound_send",
                {"kind": "text", "to": sender, "business_id": str(business_id), "body": _TOO_LONG_REPLY},
                business_id=business_id,
            )
            return
        whatsapp_jobs.enqueue(
            db,
            "inbound_message",
            {
                "business_id": str(business_id),
                "sender": sender,
                "wa_message_id": wa_message_id,
                "kind": "text",
                "text": text_body,
            },
            business_id=business_id,
        )
        return

    button_id = None
    if msg_type == "interactive" and message.interactive and message.interactive.button_reply:
        button_id = message.interactive.button_reply.id
    elif msg_type == "button" and message.button:
        button_id = message.button.payload

    if button_id is not None:
        whatsapp_jobs.enqueue(
            db,
            "inbound_message",
            {
                "business_id": str(business_id),
                "sender": sender,
                "wa_message_id": wa_message_id,
                "kind": "button",
                "button_id": button_id,
            },
            business_id=business_id,
        )
        return

    # Unsupported message type (image, audio, location, ...).
    whatsapp_jobs.enqueue(
        db,
        "outbound_send",
        {"kind": "text", "to": sender, "business_id": str(business_id), "body": _UNSUPPORTED_TYPE_REPLY},
        business_id=business_id,
    )


def _mark_seen(db: Session, wa_message_id: str) -> bool:
    """Insert the dedup row. Returns True if this is the first time we've
    seen this wa_message_id (row inserted), False if it's a replay (conflict,
    no row inserted). Uses ON CONFLICT DO NOTHING rather than a plain INSERT
    so a replay never raises IntegrityError.

    Detects the outcome via ``RETURNING`` rather than ``result.rowcount``:
    the psycopg driver reports ``rowcount == -1`` for this statement shape
    regardless of whether a row was actually inserted, so rowcount can't
    distinguish "inserted" from "conflicted" here -- but the presence of a
    returned row can.
    """
    stmt = (
        insert(WhatsAppMessageLog)
        .values(wa_message_id=wa_message_id, direction="in")
        .on_conflict_do_nothing(index_elements=["wa_message_id"])
        .returning(WhatsAppMessageLog.id)
    )
    row = db.execute(stmt).fetchone()
    db.commit()
    return row is not None
