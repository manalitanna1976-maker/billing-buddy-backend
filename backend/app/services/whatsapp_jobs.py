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
commit the caller's session.
"""

import logging
import uuid
from datetime import datetime, timedelta

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
    """Insert a new pending job and commit the caller's session."""
    job = WhatsAppJob(type=type, payload=payload, status="pending", business_id=business_id)
    db.add(job)
    db.commit()
    db.refresh(job)
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
    stale_cutoff = datetime.utcnow() - timedelta(
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
    job.claimed_at = datetime.utcnow()
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def complete(db: Session, job: WhatsAppJob) -> None:
    """Mark a job done and commit the caller's session."""
    job.status = "done"
    job.processed_at = datetime.utcnow()
    db.commit()


def fail(db: Session, job: WhatsAppJob, error: str) -> None:
    """Record a failure. Retries (back to `pending`) until
    `whatsapp_job_max_attempts` is reached, then dead-letters the job and
    alerts. Commits the caller's session. Never raises.
    """
    settings = config.get_settings()
    job.last_error = error
    if job.attempts >= settings.whatsapp_job_max_attempts:
        job.status = "dead_letter"
        db.commit()
        _alert(job)
    else:
        job.status = "pending"
        db.commit()


def _alert(job: WhatsAppJob) -> None:
    """Best-effort dead-letter notification. Always logs; also POSTs to the
    configured webhook when set. Any webhook failure is caught and logged --
    this function must never raise, since it runs on the failure path.
    """
    logger.error(
        "whatsapp job dead-lettered id=%s type=%s business=%s: %s",
        job.id,
        job.type,
        job.business_id,
        job.last_error,
    )

    webhook_url = config.get_settings().deadletter_webhook_url
    if not webhook_url:
        return

    try:
        httpx.post(
            webhook_url,
            json={
                "id": str(job.id),
                "type": job.type,
                "business_id": str(job.business_id) if job.business_id else None,
                "last_error": job.last_error,
            },
            timeout=_WEBHOOK_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("dead-letter webhook POST failed for job id=%s", job.id)
