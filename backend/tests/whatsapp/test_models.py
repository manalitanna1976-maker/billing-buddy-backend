import pytest
from sqlalchemy.exc import IntegrityError
from app.models import (WhatsAppConnection, WhatsAppAuthorizedSender,
                        WhatsAppConversation, WhatsAppMessageLog, WhatsAppJob)


def _biz(db):
    from app.models import Business
    b = Business(name="Acme"); db.add(b); db.flush(); return b


def test_one_connection_per_business(db_session):
    b = _biz(db_session)
    db_session.add(WhatsAppConnection(business_id=b.id, phone_number_id="pn1",
                                      waba_id="w1", access_token_encrypted="enc"))
    db_session.flush()
    db_session.add(WhatsAppConnection(business_id=b.id, phone_number_id="pn2",
                                      waba_id="w2", access_token_encrypted="enc"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_active_connection_per_phone_number_id(db_session):
    b1, b2 = _biz(db_session), _biz(db_session)
    db_session.add(WhatsAppConnection(business_id=b1.id, phone_number_id="pn-shared",
                                      waba_id="w1", access_token_encrypted="enc", status="active"))
    db_session.flush()
    # A second business claiming the same phone_number_id while it's still
    # active elsewhere must be rejected by the partial unique index --
    # this is the exact Meta-number-reassignment scenario `status='active'`
    # exists to guard against.
    db_session.add(WhatsAppConnection(business_id=b2.id, phone_number_id="pn-shared",
                                      waba_id="w2", access_token_encrypted="enc", status="active"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_disconnected_connection_does_not_block_reuse_of_phone_number_id(db_session):
    b1, b2 = _biz(db_session), _biz(db_session)
    db_session.add(WhatsAppConnection(business_id=b1.id, phone_number_id="pn-freed",
                                      waba_id="w1", access_token_encrypted="enc", status="disconnected"))
    db_session.flush()
    # A *disconnected* row with the same phone_number_id is fine -- the
    # partial index only constrains status='active' rows.
    db_session.add(WhatsAppConnection(business_id=b2.id, phone_number_id="pn-freed",
                                      waba_id="w2", access_token_encrypted="enc", status="active"))
    db_session.flush()  # must not raise


def test_sender_unique_per_business_not_global(db_session):
    b1, b2 = _biz(db_session), _biz(db_session)
    db_session.add_all([
        WhatsAppAuthorizedSender(business_id=b1.id, phone_e164="+911", enrolled_by="a@x"),
        WhatsAppAuthorizedSender(business_id=b2.id, phone_e164="+911", enrolled_by="b@x"),
    ])
    db_session.flush()  # same number, different businesses -> OK
    db_session.add(WhatsAppAuthorizedSender(business_id=b1.id, phone_e164="+911", enrolled_by="a@x"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_message_log_dedup_unique(db_session):
    db_session.add(WhatsAppMessageLog(wa_message_id="wamid.1", direction="in"))
    db_session.flush()
    db_session.add(WhatsAppMessageLog(wa_message_id="wamid.1", direction="in"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_message_log_has_no_body_column(db_session):
    cols = {c.name for c in WhatsAppMessageLog.__table__.columns}
    assert "body" not in cols and "text" not in cols and "content" not in cols
