"""Standalone worker process for the WhatsApp -> invoice job queue (Task B4).

Run as ``python -m app.workers.whatsapp_worker``. The loop claims one
``whatsapp_jobs`` row at a time (``SELECT ... FOR UPDATE SKIP LOCKED``), so any
number of these processes can run side by side without double-processing a job.

Dispatch by ``job.type``:

* ``inbound_message`` -> ``whatsapp_flow.handle_inbound`` produces a list of
  outbound reply payloads; each is enqueued as its own ``outbound_send`` job
  (passing ``business_id`` explicitly -- an ``outbound_send`` job with a NULL
  ``business_id`` is invisible on the C2 dead-letter admin endpoint), then the
  inbound job is completed.
* ``outbound_send`` -> ``whatsapp_outbound.handle_outbound`` does the real Meta
  adapter send (renders + uploads the PDF for a ``document`` payload), records an
  ``out`` message-log row, and may enqueue a follow-up ``document`` job; the
  worker then marks the job done.

``main`` also runs ``whatsapp_retention.retention_sweep`` roughly every 5 minutes
while the queue is idle (hard-deletes aged conversations / finished jobs so no
WhatsApp-draft PII persists past 24h, resets stranded confirms, folds in the
rate-limit / token-revocation prunes).

Any exception during dispatch is handed to ``whatsapp_jobs.fail``, which rolls
back the aborted transaction, records the error, and either re-queues the job
(``pending``) or dead-letters it once ``whatsapp_job_max_attempts`` is hit.
``fail`` never raises, so the loop keeps going.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services import whatsapp_jobs as jobs
from app.services.whatsapp_flow import handle_inbound
from app.services.whatsapp_outbound import handle_outbound
from app.services.whatsapp_retention import retention_sweep

logger = logging.getLogger(__name__)

_IDLE_SLEEP_SECONDS = 2
_RETENTION_SWEEP_INTERVAL_SECONDS = 300


def run_once(db: Session) -> bool:
    """Claim and process a single job.

    Returns ``True`` if a job was claimed (and handled or failed), ``False`` if
    the queue had nothing runnable. Tests drive this seam directly rather than
    spinning ``main``'s loop.
    """
    job = jobs.claim_next(db)
    if job is None:
        return False

    try:
        if job.type == "inbound_message":
            payloads = handle_inbound(db, job.payload)
            # One transaction: conv mutations + outbound jobs + completion commit
            # together, so a crash mid-dispatch cannot leave the inbound job
            # re-claimable and re-run handle_inbound (another Claude call +
            # duplicate replies). `build` adds without committing.
            for payload in payloads:
                jobs.build(db, "outbound_send", payload, job.business_id)
            job.status = "done"
            job.processed_at = datetime.utcnow()
            db.commit()
            logger.info(
                "whatsapp worker processed job=%s type=inbound_message business=%s "
                "replies=%d",
                job.id,
                job.business_id,
                len(payloads),
            )
        elif job.type == "outbound_send":
            # handle_outbound sends via the Meta adapter and, in ONE transaction
            # (the B4 precedent), writes the message-log row, builds any
            # follow-up document job, AND marks this job done -- so a crash after
            # a successful send can't re-claim the job and double the message /
            # follow-up job / log row.
            handle_outbound(db, job)
            logger.info(
                "whatsapp worker processed job=%s type=outbound_send business=%s "
                "kind=%s",
                job.id,
                job.business_id,
                job.payload.get("kind"),
            )
        else:
            jobs.fail(db, job, f"unknown whatsapp job type {job.type!r}")
    except Exception as exc:  # noqa: BLE001 -- fail() records + re-queues/dead-letters
        jobs.fail(db, job, repr(exc))

    return True


def main() -> None:  # pragma: no cover -- exercised via run_once in tests
    logger.info("whatsapp worker starting")
    last_sweep = 0.0
    while True:
        db = SessionLocal()
        try:
            worked = run_once(db)
            now = time.monotonic()
            if not worked and now - last_sweep > _RETENTION_SWEEP_INTERVAL_SECONDS:
                retention_sweep(db)
                last_sweep = now
        except Exception:  # noqa: BLE001 -- a DB blip must not kill the worker
            logger.exception("worker iteration failed")
            worked = False
        finally:
            db.close()
        if not worked:
            time.sleep(_IDLE_SLEEP_SECONDS)


if __name__ == "__main__":  # pragma: no cover
    main()
