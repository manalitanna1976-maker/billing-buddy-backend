import time

from app import token_revocation as tr


def test_revoked_then_reported_revoked(db_session):
    tr.revoke_token(db_session, "jti-1", exp=time.time() + 3600)
    assert tr.is_token_revoked(db_session, "jti-1") is True
    assert tr.is_token_revoked(db_session, "jti-2") is False


def test_expired_revocation_is_pruned_on_write(db_session):
    tr.revoke_token(db_session, "old", exp=time.time() - 10)
    tr.revoke_token(db_session, "new", exp=time.time() + 3600)
    assert tr.is_token_revoked(db_session, "old") is False
