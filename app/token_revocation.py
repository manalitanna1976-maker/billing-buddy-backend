"""In-memory store of revoked JWT ids (jti), backing POST /auth/logout.

Access tokens are stateless by design (see app/security.py) -- signing them
doesn't let the server invalidate one on demand. To support logout, every
token carries a unique `jti`; logging out records that jti here, and
get_current_business (app/deps.py) rejects any token whose jti shows up in
this store, even if the signature and expiry are otherwise still valid.

v1 limitation: this is a process-local in-memory dict, matching the same
constraint documented in app/rate_limit.py -- there is no Redis or other
shared cache in this stack. It is correct for the single-instance deployment
this app currently runs as: logging out invalidates the token everywhere,
because there's only one process to invalidate it against. If the app is
ever horizontally scaled, each instance would hold its own revocation list
and a token revoked on instance A would still work against instance B --
this needs to move to a shared store (e.g. Redis) at that point. Not solved
here by design per the task scope.
"""

import threading
import time

_lock = threading.Lock()
_revoked: dict[str, float] = {}  # jti -> token expiry (epoch seconds)


def _prune_locked(now: float) -> None:
    """Must be called while holding `_lock`. A revoked jti only needs to be
    remembered until the token itself would have expired anyway -- after
    that it's rejected by signature/expiry checks regardless."""
    expired = [jti for jti, exp in _revoked.items() if exp <= now]
    for jti in expired:
        del _revoked[jti]


def revoke_token(jti: str, exp: float) -> None:
    with _lock:
        _prune_locked(time.time())
        _revoked[jti] = exp


def is_token_revoked(jti: str) -> bool:
    with _lock:
        _prune_locked(time.time())
        return jti in _revoked


def reset_all_state() -> None:
    """Test-only helper: clears all revocation state so one test's logout
    can't bleed into another (see tests/conftest.py)."""
    with _lock:
        _revoked.clear()
