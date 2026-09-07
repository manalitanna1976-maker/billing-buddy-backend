"""Postgres-backed sliding-window rate limiter for login attempts.

Policy (see backend/app/routers/auth.py):
  - Per email: 10 failed attempts / 15 minutes. Stops "hammer one account"
    password guessing regardless of how many source IPs the attacker uses.
  - Per IP:    30 failed attempts / 15 minutes, across *any* emails. Stops
    "spray many accounts from one IP" credential stuffing, where each
    individual email is only tried a handful of times (never enough to
    trip the per-email cap on its own) but the same client is hammering
    many different accounts.
  A successful login resets that email's failed-attempt counter, so a
  legitimate user who fat-fingered their password a few times isn't
  penalized once they get it right. Only failed attempts count toward
  either limit.

Shared-state design: attempts are rows in the `rate_limit_events` table
(one per failed login per bucket_key), not a process-local dict. This is
what lets the future WhatsApp worker process (separate from the web
process) share the same counters. For the current single-instance
deployment the behaviour is unchanged.

The email bucket_key is a SHA-256 digest of the normalized email, not the
raw address: it keeps the key fixed-width (so an over-long email can't
overflow `bucket_key` and 500 the login) and keeps raw email addresses
out of this table.

Growth control without a scheduler: `record_failed_login` does one global
time-based prune on every write, deleting every row older than the longest
window. That bounds the table regardless of whether any particular email
is ever retried. `sweep_expired` exposes the same prune with an identical
predicate for a future worker loop; nothing calls it yet.

Transaction contract: `record_event`, `record_failed_login`,
`reset_failed_logins`, `sweep_expired`, and `reset_all_state` own their own
commit -- they call `db.commit()` on the caller's session. `add_events` and
`count_in_window` do NOT commit -- the caller owns the transaction (this is
what lets the webhook fold a rate-limit write into the same transaction as
its dedup + job inserts). Do not call the committing helpers mid-transaction
on a session that has other uncommitted work you don't want committed.
"""

import hashlib
from datetime import timedelta

from app.time_utils import utcnow

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RateLimitEvent

EMAIL_MAX_ATTEMPTS = 10
EMAIL_WINDOW_SECONDS = 15 * 60

IP_MAX_ATTEMPTS = 30
IP_WINDOW_SECONDS = 15 * 60

# Account creation: cap per IP so signup can't be used to mass-create
# businesses / exhaust the DB.
SIGNUP_MAX_ATTEMPTS = 20
SIGNUP_WINDOW_SECONDS = 60 * 60

# The WhatsApp webhook reuses the same `rate_limit_events` table for its
# per-sender / per-business throttling. Keeping its window here (rather than a
# private constant in the webhook router) means `_global_prune` / `sweep_expired`
# never age out a row that the webhook's `count_in_window` still needs.
WHATSAPP_WINDOW_SECONDS = 15 * 60


def _email_key(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"email:{digest}"


def _ip_key(ip: str) -> str:
    return f"ip:{ip}"


def _signup_key(ip: str) -> str:
    return f"signup:{ip}"


def is_signup_rate_limited(db: Session, ip: str) -> bool:
    """True if this IP has created too many accounts in the window."""
    return (
        count_in_window(db, _signup_key(ip), SIGNUP_WINDOW_SECONDS) >= SIGNUP_MAX_ATTEMPTS
    )


def record_signup_attempt(db: Session, ip: str) -> None:
    """Record one account-creation attempt against the IP bucket. Commits."""
    add_events(db, [_signup_key(ip)])
    db.commit()


def _global_prune(db: Session) -> None:
    """Delete every row older than the longest configured window. A single
    global delete run on every write, so orphan buckets that are never
    retried still age out without a scheduler.
    """
    cutoff = utcnow() - timedelta(
        seconds=max(EMAIL_WINDOW_SECONDS, IP_WINDOW_SECONDS, WHATSAPP_WINDOW_SECONDS, SIGNUP_WINDOW_SECONDS)
    )
    db.execute(delete(RateLimitEvent).where(RateLimitEvent.occurred_at <= cutoff))


# --- generic sliding-window seam -------------------------------------------------
# `record_event` / `count_in_window` are bucket-key agnostic: the login helpers
# below are just one caller (email + IP buckets); a future WhatsApp worker can
# reuse the same table and semantics for per-sender / per-business throttling.


def add_events(db: Session, bucket_keys: list[str]) -> None:
    """Insert one event row per bucket key and run the global prune. Does NOT
    commit -- the caller owns the transaction.
    """
    for k in bucket_keys:
        db.add(RateLimitEvent(bucket_key=k, occurred_at=utcnow()))
    db.flush()
    _global_prune(db)


def record_event(db: Session, bucket_key: str) -> None:
    """Insert one event row for `bucket_key`, run the global time-based prune,
    and commit the caller's session.
    """
    add_events(db, [bucket_key])
    db.commit()


def count_in_window(db: Session, bucket_key: str, window_seconds: int) -> int:
    """Number of events recorded for `bucket_key` within the last
    `window_seconds` seconds.
    """
    threshold = utcnow() - timedelta(seconds=window_seconds)
    return db.execute(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(
            RateLimitEvent.bucket_key == bucket_key,
            RateLimitEvent.occurred_at > threshold,
        )
    ).scalar_one()


def is_login_rate_limited(db: Session, email: str, ip: str) -> bool:
    """True if this email or this IP has already hit its failed-attempt cap."""
    if count_in_window(db, _email_key(email), EMAIL_WINDOW_SECONDS) >= EMAIL_MAX_ATTEMPTS:
        return True
    if count_in_window(db, _ip_key(ip), IP_WINDOW_SECONDS) >= IP_MAX_ATTEMPTS:
        return True
    return False


def record_failed_login(db: Session, email: str, ip: str) -> None:
    """Record one failed attempt against both the email and IP buckets, then
    prune every row older than the longest window.

    Commits the caller's session.
    """
    add_events(db, [_email_key(email), _ip_key(ip)])
    db.commit()


def reset_failed_logins(db: Session, email: str) -> None:
    """Called on a successful login: forgive that email's failed attempts.

    Commits the caller's session.
    """
    db.execute(delete(RateLimitEvent).where(RateLimitEvent.bucket_key == _email_key(email)))
    db.commit()


def sweep_expired(db: Session) -> int:
    """Delete rows older than the longest window. Returns rows deleted. For a
    future worker retention loop -- unused now. Uses the same predicate as the
    global prune in `record_failed_login`.

    Commits the caller's session.
    """
    cutoff = utcnow() - timedelta(
        seconds=max(EMAIL_WINDOW_SECONDS, IP_WINDOW_SECONDS, WHATSAPP_WINDOW_SECONDS, SIGNUP_WINDOW_SECONDS)
    )
    result = db.execute(
        delete(RateLimitEvent).where(RateLimitEvent.occurred_at <= cutoff)
    )
    db.commit()
    return result.rowcount


def reset_all_state(db: Session) -> None:
    """Test-only helper: clears all limiter state so failed-login hammering
    in one test can't bleed into another (see tests/conftest.py).

    Commits the caller's session.
    """
    db.execute(delete(RateLimitEvent))
    db.commit()
