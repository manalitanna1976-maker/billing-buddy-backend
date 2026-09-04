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

Growth control without a scheduler: `record_failed_login` opportunistically
deletes that bucket's rows that have aged out of the window after inserting
the new ones. `sweep_expired` exposes a broader prune for a future worker
loop; nothing calls it yet.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import RateLimitEvent

EMAIL_MAX_ATTEMPTS = 10
EMAIL_WINDOW_SECONDS = 15 * 60

IP_MAX_ATTEMPTS = 30
IP_WINDOW_SECONDS = 15 * 60


def _email_key(email: str) -> str:
    return f"email:{email.strip().lower()}"


def _ip_key(ip: str) -> str:
    return f"ip:{ip}"


def _count_within(db: Session, bucket_key: str, window_seconds: int) -> int:
    threshold = datetime.utcnow() - timedelta(seconds=window_seconds)
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
    if _count_within(db, _email_key(email), EMAIL_WINDOW_SECONDS) >= EMAIL_MAX_ATTEMPTS:
        return True
    if _count_within(db, _ip_key(ip), IP_WINDOW_SECONDS) >= IP_MAX_ATTEMPTS:
        return True
    return False


def record_failed_login(db: Session, email: str, ip: str) -> None:
    """Record one failed attempt against both the email and IP buckets, then
    prune each bucket's rows that have aged out of its window."""
    now = datetime.utcnow()
    email_key = _email_key(email)
    ip_key = _ip_key(ip)
    db.add(RateLimitEvent(bucket_key=email_key, occurred_at=now))
    db.add(RateLimitEvent(bucket_key=ip_key, occurred_at=now))
    db.flush()

    for bucket_key, window_seconds in (
        (email_key, EMAIL_WINDOW_SECONDS),
        (ip_key, IP_WINDOW_SECONDS),
    ):
        threshold = datetime.utcnow() - timedelta(seconds=window_seconds)
        db.execute(
            delete(RateLimitEvent).where(
                RateLimitEvent.bucket_key == bucket_key,
                RateLimitEvent.occurred_at <= threshold,
            )
        )
    db.commit()


def reset_failed_logins(db: Session, email: str) -> None:
    """Called on a successful login: forgive that email's failed attempts."""
    db.execute(delete(RateLimitEvent).where(RateLimitEvent.bucket_key == _email_key(email)))
    db.commit()


def sweep_expired(db: Session) -> int:
    """Delete rows older than the longest window. Returns rows deleted. For a
    future worker retention loop -- unused now."""
    longest_window = max(EMAIL_WINDOW_SECONDS, IP_WINDOW_SECONDS)
    threshold = datetime.utcnow() - timedelta(seconds=longest_window)
    result = db.execute(
        delete(RateLimitEvent).where(RateLimitEvent.occurred_at <= threshold)
    )
    db.commit()
    return result.rowcount


def reset_all_state(db: Session) -> None:
    """Test-only helper: clears all limiter state so failed-login hammering
    in one test can't bleed into another (see tests/conftest.py)."""
    db.execute(delete(RateLimitEvent))
    db.commit()
