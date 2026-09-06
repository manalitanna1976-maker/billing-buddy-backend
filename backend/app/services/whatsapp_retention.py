"""Task B6: the periodic retention sweep for the WhatsApp -> invoice feature.

The spec's retention promise: "no customer PII from a WhatsApp draft persists
beyond 24h". Three tables can hold that PII:

* ``whatsapp_conversations.draft_payload`` -- the in-flight draft (customer name,
  amounts).
* ``whatsapp_jobs.payload`` -- the *raw inbound message text* for
  ``inbound_message`` jobs (customer name, amounts, possibly GSTIN/PAN). This is
  a real body-content store the original spec's sweep didn't account for.
* ``whatsapp_message_log`` -- never stores a body, but its rows are orphaned
  garbage once their conversation is gone, and the dedup ledger otherwise grows
  forever (rows older than 30 days are dropped).

``retention_sweep`` also resets **stranded confirms** (a worker crash between
``handle_confirm``'s ``state="confirmed"`` commit and its atomic invoice commit
leaves a conversation stuck in ``confirmed`` with ``invoice_id IS NULL``; left
alone, a stale Edit/Confirm could re-confirm off the frozen draft) and folds in
the two prereq security sweeps (``rate_limit`` / ``token_revocation``).

Timestamps use ``datetime.utcnow()`` on the Python side to match the rest of the
codebase (naive UTC everywhere). Returns a counts dict for the worker log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app import rate_limit, token_revocation
from app.models import WhatsAppConversation, WhatsAppJob, WhatsAppMessageLog

logger = logging.getLogger(__name__)


def retention_sweep(db: Session) -> dict:
    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_15m = now - timedelta(minutes=15)
    cutoff_30d = now - timedelta(days=30)

    # 1. Reset stranded confirms BEFORE the delete, so the now-terminal rows can
    #    then age out via the 24h expiry rule in step 2 on a later sweep.
    stranded = db.execute(
        update(WhatsAppConversation)
        .where(
            WhatsAppConversation.updated_at < cutoff_15m,
            or_(
                # a worker crash between handle_confirm's state="confirmed"
                # commit and its atomic invoice commit
                (WhatsAppConversation.state == "confirmed")
                & WhatsAppConversation.invoice_id.is_(None),
                # the confirm split-window race (I2): state dragged back to
                # collecting while invoice_id stayed set -- a combination no
                # reset path in whatsapp_flow covers
                (WhatsAppConversation.state == "collecting")
                & WhatsAppConversation.invoice_id.is_not(None),
            ),
        )
        .values(state="terminal")
        .execution_options(synchronize_session=False)
    ).rowcount

    # Conversations to hard-delete: expired >24h ago, OR confirmed and untouched
    # for >24h (a completed draft we no longer need).
    doomed_conv_predicate = (WhatsAppConversation.expires_at < cutoff_24h) | (
        (WhatsAppConversation.state == "confirmed")
        & (WhatsAppConversation.updated_at < cutoff_24h)
    )

    # 2. Delete message-log rows BEFORE the conversations they point at (the FK
    #    has no ON DELETE): rows linked to a doomed conversation, rows already
    #    dangling, and -- since `conversation_id` is nullable and always NULL in
    #    practice, so the linked/dangling predicates never match a real row --
    #    any row older than 30 days, so this dedup ledger stays bounded.
    doomed_conv_ids = select(WhatsAppConversation.id).where(doomed_conv_predicate)
    message_logs = db.execute(
        delete(WhatsAppMessageLog)
        .where(
            or_(
                (
                    WhatsAppMessageLog.conversation_id.is_not(None)
                    & or_(
                        WhatsAppMessageLog.conversation_id.in_(doomed_conv_ids),
                        WhatsAppMessageLog.conversation_id.not_in(
                            select(WhatsAppConversation.id)
                        ),
                    )
                ),
                WhatsAppMessageLog.created_at < cutoff_30d,
            )
        )
        .execution_options(synchronize_session=False)
    ).rowcount

    # 3. Hard-delete the aged-out conversations.
    conversations = db.execute(
        delete(WhatsAppConversation)
        .where(doomed_conv_predicate)
        .execution_options(synchronize_session=False)
    ).rowcount

    # 4. Hard-delete finished jobs (payload carries raw inbound PII). `dead_letter`
    #    rows may never have completed -> COALESCE to created_at.
    job_rows = db.execute(
        delete(WhatsAppJob)
        .where(
            WhatsAppJob.status.in_(("done", "dead_letter")),
            func.coalesce(WhatsAppJob.processed_at, WhatsAppJob.created_at) < cutoff_24h,
        )
        .execution_options(synchronize_session=False)
    ).rowcount

    # 5. Fold in the prereq security sweeps. Each commits the caller's session
    #    (which also persists steps 1-4); the trailing commit is then a no-op but
    #    kept for clarity / future reordering safety.
    revoked_tokens = token_revocation.sweep_expired(db)
    rate_limit_events = rate_limit.sweep_expired(db)

    db.commit()

    counts = {
        "conversations": conversations,
        "message_logs": message_logs,
        "jobs": job_rows,
        "stranded_confirms": stranded,
        "revoked_tokens": revoked_tokens,
        "rate_limit_events": rate_limit_events,
    }
    logger.info("whatsapp retention sweep: %s", counts)
    return counts
