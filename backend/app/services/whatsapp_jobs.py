"""Postgres-backed durable job queue for WhatsApp inbound/outbound processing.

Design: `whatsapp_jobs` is a plain table, not a broker. Workers (possibly many,
possibly in separate processes) call `claim_next` in a loop; the claim is a
single `SELECT ... FOR UPDATE SKIP LOCKED` + status update inside one
transaction, so two workers racing for the same row never both win it -- the
loser's SELECT simply skips the locked row and (if nothing else qualifies)
returns no rows. A `processing` row whose claim has gone stale (worker died
mid-job) becomes claimable again after `whatsapp_job_stale_claim_seconds`,
so a crashed worker can't strand a job forever.

Retry policy: `fail` puts the job back to `pending` (to be re-claimed) until
`attempts` reaches `settings.whatsapp_job_max_attempts`, at which point it is
moved to `dead_letter` and `_alert` is called. `_alert` always logs; it also
best-effort POSTs to `settings.deadletter_webhook_url` when configured, but a
webhook failure must never take down the caller (`fail` itself must not
raise), so any exception there is caught and logged, never re-raised.

Transaction contract: `enqueue`, `claim_next`, `complete`, and `fail` each
commit the caller's session. `build` does NOT commit -- the caller owns the
transaction (the webhook folds the job insert into its per-message tx).
"""

import logging
import uuid
from datetime import timedelta

from app.time_utils import utcnow

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import WhatsAppJob

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_SECONDS = 5


def enqueue(
    db: Session,
    type: str,
    payload: dict,
    business_id: uuid.UUID | None = None,
) -> WhatsAppJob:
    """Insert a new pending job and commit the caller's session.

    `payload` may contain raw inbound message text (customer names, amounts,
    GSTIN/PAN). Rows are hard-deleted 24h after `processed_at` by the worker's
    retention sweep (Task B6) -- do not treat this table as durable storage,
    and never return `payload` verbatim through an API (see the C2 dead-letter
    endpoint's redacted view).

    When `business_id` is not passed, it is derived from `payload["business_id"]`
    if present, so a re-enqueued `outbound_send` job stays visible on the C2
    admin endpoint; a job that still ends up with no `business_id` is logged.
    """
    job = build(db, type, payload, business_id)
    db.commit()
    db.refresh(job)
    return job


def build(
    db: Session,
    type: str,
    payload: dict,
    business_id: uuid.UUID | None = None,
) -> WhatsAppJob:
    """Add a pending job to the session but do NOT commit -- the caller owns the
    transaction. The webhook uses this to fold the job insert into the same
    transaction as its dedup row + rate-limit events (one commit per message).

    Shares `enqueue`'s `business_id`-from-payload derivation and no-business_id
    warning.
    """
    if business_id is None and isinstance(payload, dict) and payload.get("business_id"):
        try:
            business_id = uuid.UUID(str(payload["business_id"]))
        except (ValueError, TypeError):
            business_id = None
    if business_id is None:
        logger.warning("whatsapp job enqueued with no business_id (type=%s)", type)
    job = WhatsAppJob(type=type, payload=payload, status="pending", business_id=business_id)
    db.add(job)
    return job


def claim_next(db: Session) -> WhatsAppJob | None:
    """Atomically claim the next runnable job, or return None if there isn't
    one.

    Runnable means: status='pending', or status='processing' with a claim
    that has gone stale (the worker that took it presumably died). The
    SELECT and the status update happen in one transaction -- no commit in
    between -- so `FOR UPDATE SKIP LOCKED` actually protects the row from a
    concurrent claimer for the whole claim, not just the read.
    """
    settings = config.get_settings()
    stale_cutoff = utcnow() - timedelta(
        seconds=settings.whatsapp_job_stale_claim_seconds
    )

    stmt = (
        select(WhatsAppJob)
        .where(
            (WhatsAppJob.status == "pending")
            | ((WhatsAppJob.status == "processing") & (WhatsAppJob.claimed_at < stale_cutoff))
        )
        .order_by(WhatsAppJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = db.execute(stmt).scalars().first()
    if job is None:
        return None

    job.status = "processing"
    job.claimed_at = utcnow()
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def complete(db: Session, job: WhatsAppJob) -> None:
    """Mark a job done and commit the caller's session."""
    job.status = "done"
    job.processed_at = utcnow()
    db.commit()


def fail(
    db: Session,
    job: WhatsAppJob,
    error: str,
    dead_letter_now: bool = False,
) -> None:
    """Record a failure. Retries (back to `pending`) until
    `whatsapp_job_max_attempts` is reached, then dead-letters the job and
    alerts. Commits the caller's session. Never raises.

    `dead_letter_now=True` skips the attempts check and dead-letters
    immediately -- for a poison pill (e.g. an unknown job type) that will never
    succeed, so it must not burn every claim cycle first (M5).
    """
    settings = config.get_settings()
    # The failed handler may have left the session's transaction aborted (a bad
    # DB write before it raised). Roll it back so our own commit can run, then
    # re-fetch the job -- rollback expires/detaches the instance we were handed.
    db.rollback()
    job = db.get(WhatsAppJob, job.id)
    if job is None:
        return
    job.last_error = error
    if dead_letter_now or job.attempts >= settings.whatsapp_job_max_attempts:
        job.status = "dead_letter"
        # An inbound_message that dies for good must still tell the owner
        # something came through and failed -- otherwise a Claude outage means
        # they text an invoice and hear nothing ever (I5, plan B4). Fold the
        # reply into THIS transaction. Never for outbound_send (no reply loop).
        if job.type == "inbound_message" and isinstance(job.payload, dict):
            biz = job.payload.get("business_id")
            sender = job.payload.get("sender")
            if biz and sender:
                try:
                    biz_uuid = uuid.UUID(str(biz))
                except (ValueError, TypeError):
                    biz_uuid = None
                build(
                    db,
                    "outbound_send",
                    {
                        "kind": "text",
                        "to": sender,
                        "business_id": str(biz),
                        "body": (
                            "Couldn't read that message — please try again or "
                            "use the web app."
                        ),
                    },
                    business_id=biz_uuid,
                )
        # Snapshot the fields _alert needs BEFORE the commit, so _alert never
        # triggers a lazy reload / DetachedInstanceError on an expired instance.
        alert_snapshot = {
            "id": job.id,
            "type": job.type,
            "business_id": job.business_id,
            "last_error": job.last_error,
        }
        db.commit()
        _alert(alert_snapshot)
    else:
        job.status = "pending"
        db.commit()


def _alert(snapshot: dict) -> None:
    """Best-effort dead-letter notification. Always logs; also POSTs to the
    configured webhook when set. Any webhook failure is caught and logged --
    this function must never raise, since it runs on the failure path.

    Takes a plain dict snapshot (not the ORM object) so it can't trigger a
    reload on an expired/detached instance.
    """
    logger.error(
        "whatsapp job dead-lettered id=%s type=%s business=%s: %s",
        snapshot["id"],
        snapshot["type"],
        snapshot["business_id"],
        snapshot["last_error"],
    )

    webhook_url = config.get_settings().deadletter_webhook_url
    if not webhook_url:
        return

    # The webhook is a third-party transfer (DPDP concern) and `last_error` can
    # carry model-produced strings derived from message content -- truncate it
    # here (M4). The full string stays in the DB column and the ERROR log above.
    last_error = snapshot["last_error"]
    if isinstance(last_error, str):
        last_error = last_error[:200]

    try:
        httpx.post(
            webhook_url,
            json={
                "id": str(snapshot["id"]),
                "type": snapshot["type"],
                "business_id": str(snapshot["business_id"]) if snapshot["business_id"] else None,
                "last_error": last_error,
            },
            timeout=_WEBHOOK_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("dead-letter webhook POST failed for job id=%s", snapshot["id"])
