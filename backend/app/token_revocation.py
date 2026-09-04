"""Postgres-backed store of revoked JWT ids (jti), backing POST /auth/logout.

Access tokens are stateless by design (see app/security.py) -- signing them
doesn't let the server invalidate one on demand. To support logout, every
token carries a unique `jti`; logging out records that jti here, and
get_current_business (app/deps.py) rejects any token whose jti shows up in
this store, even if the signature and expiry are otherwise still valid.

Shared-state design: revocations live in the `revoked_tokens` table, not a
process-local dict. This is what lets the future WhatsApp worker process
(separate from the web process) see a token revoked by the web process and
vice versa. For the current single-instance deployment the behaviour is
unchanged: logging out invalidates the token everywhere, because every
process reads the same table.

Growth control without a scheduler: `revoke_token` opportunistically deletes
rows whose token has already expired (a revoked jti only needs to be
remembered until its own expiry -- after that it's rejected by
signature/expiry checks regardless). `sweep_expired` exposes the same prune
for a future worker loop; nothing calls it yet.

Transaction contract: the mutating helpers here (`revoke_token`,
`sweep_expired`, `reset_all_state`) own their own commit -- they call
`db.commit()` on the caller's session. Do not call them mid-transaction on
a session that has other uncommitted work you don't want committed.
"""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import RevokedToken


def revoke_token(db: Session, jti: str, exp: float) -> None:
    """Record `jti` as revoked until `exp` (a Unix timestamp, the JWT `exp`
    claim). Opportunistically prunes already-expired rows to bound growth.
    The insert is an idempotent upsert so a concurrent duplicate logout of
    the same jti can't race into a primary-key violation.

    Commits the caller's session.
    """
    now = datetime.utcnow()
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
    db.execute(
        pg_insert(RevokedToken)
        .values(jti=jti, expires_at=datetime.utcfromtimestamp(exp))
        .on_conflict_do_nothing(index_elements=["jti"])
    )
    db.commit()


def is_token_revoked(db: Session, jti: str) -> bool:
    """True if `jti` was logged out and its token hasn't expired yet."""
    row = db.execute(
        select(RevokedToken.jti).where(
            RevokedToken.jti == jti,
            RevokedToken.expires_at > datetime.utcnow(),
        )
    ).first()
    return row is not None


def sweep_expired(db: Session) -> int:
    """Delete revocation rows whose token has already expired. Returns the
    number of rows deleted. For a future worker retention loop -- unused now.

    Commits the caller's session.
    """
    result = db.execute(
        delete(RevokedToken).where(RevokedToken.expires_at <= datetime.utcnow())
    )
    db.commit()
    return result.rowcount


def reset_all_state(db: Session) -> None:
    """Test-only helper: clears all revocation state so one test's logout
    can't bleed into another (see tests/conftest.py).

    Commits the caller's session.
    """
    db.execute(delete(RevokedToken))
    db.commit()
