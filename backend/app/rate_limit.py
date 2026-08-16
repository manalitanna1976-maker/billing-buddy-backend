"""In-memory sliding-window rate limiter for login attempts.

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

v1 limitation: this state is a process-local in-memory dict (matching the
rest of the app -- see config.py / main.py, there is no Redis or other
shared cache in the stack). It is correct for the single-instance
deployment this app currently runs as. If the app is ever horizontally
scaled to multiple instances behind a load balancer, each instance would
track its own counters independently and the effective limit would be
(per-instance limit x instance count) -- this would need to move to a
shared store (e.g. Redis) at that point. Not solved here by design per
the task scope.
"""

import threading
import time
from collections import defaultdict

EMAIL_MAX_ATTEMPTS = 10
EMAIL_WINDOW_SECONDS = 15 * 60

IP_MAX_ATTEMPTS = 30
IP_WINDOW_SECONDS = 15 * 60

_lock = threading.Lock()
_attempts: dict[str, list[float]] = defaultdict(list)


def _email_key(email: str) -> str:
    return f"email:{email.strip().lower()}"


def _ip_key(ip: str) -> str:
    return f"ip:{ip}"


def _prune_locked(key: str, window_seconds: float, now: float) -> list[float]:
    """Must be called while holding `_lock`. Drops timestamps outside the
    window and returns what's left (also updating `_attempts` in place)."""
    kept = [t for t in _attempts.get(key, ()) if now - t < window_seconds]
    if kept:
        _attempts[key] = kept
    else:
        _attempts.pop(key, None)
    return kept


def is_login_rate_limited(email: str, ip: str) -> bool:
    """True if this email or this IP has already hit its failed-attempt cap."""
    now = time.monotonic()
    with _lock:
        if len(_prune_locked(_email_key(email), EMAIL_WINDOW_SECONDS, now)) >= EMAIL_MAX_ATTEMPTS:
            return True
        if len(_prune_locked(_ip_key(ip), IP_WINDOW_SECONDS, now)) >= IP_MAX_ATTEMPTS:
            return True
        return False


def record_failed_login(email: str, ip: str) -> None:
    now = time.monotonic()
    with _lock:
        _attempts[_email_key(email)].append(now)
        _attempts[_ip_key(ip)].append(now)


def reset_failed_logins(email: str) -> None:
    """Called on a successful login: forgive that email's failed attempts."""
    with _lock:
        _attempts.pop(_email_key(email), None)


def reset_all_state() -> None:
    """Test-only helper: clears all limiter state so failed-login hammering
    in one test can't bleed into another (see tests/conftest.py)."""
    with _lock:
        _attempts.clear()
