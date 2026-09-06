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
* ``outbound_send`` -> Task B6 (the Meta adapter send). For now a stub that just
  completes the job.

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

logger = logging.getLogger(__name__)

_IDLE_SLEEP_SECONDS = 2


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
        elif job.type == "outbound_send":
            # TODO(B6): real Meta adapter send via app.services.whatsapp_outbound.
            jobs.complete(db, job)
        else:
            jobs.fail(db, job, f"unknown whatsapp job type {job.type!r}")
    except Exception as exc:  # noqa: BLE001 -- fail() records + re-queues/dead-letters
        jobs.fail(db, job, repr(exc))

    return True


def main() -> None:  # pragma: no cover -- exercised via run_once in tests
    logger.info("whatsapp worker starting")
    while True:
        db = SessionLocal()
        try:
            worked = run_once(db)
        except Exception:  # noqa: BLE001 -- a DB blip must not kill the worker
            logger.exception("worker iteration failed")
            worked = False
        finally:
            db.close()
        if not worked:
            time.sleep(_IDLE_SLEEP_SECONDS)
        # TODO(B6): every ~30s call app.services.whatsapp_retention.retention_sweep(db)


if __name__ == "__main__":  # pragma: no cover
    main()
