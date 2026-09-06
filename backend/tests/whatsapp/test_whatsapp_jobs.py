import uuid

import pytest
from sqlalchemy import text

from app import config
from app.db import SessionLocal
from app.models import WhatsAppJob
from app.services import whatsapp_jobs as q


_BASE_SETTINGS = config.get_settings()


def _settings_with(**overrides):
    data = _BASE_SETTINGS.model_dump()
    data.update(overrides)
    return config.Settings(**data)


def test_enqueue_then_claim(db_session):
    q.enqueue(db_session, "inbound_message", {"x": 1})
    job = q.claim_next(db_session)
    assert job.type == "inbound_message" and job.status == "processing" and job.attempts == 1


def test_claim_next_returns_none_when_empty(db_session):
    assert q.claim_next(db_session) is None


def test_skip_locked_two_sessions_never_double_claim(db_session):
    q.enqueue(db_session, "inbound_message", {"n": 1})
    s1, s2 = SessionLocal(), SessionLocal()
    try:
        j1 = q.claim_next(s1)
        j2 = q.claim_next(s2)  # first claim holds/leaves the row; second must get None
        assert j1 is not None and j2 is None
    finally:
        s1.close()
        s2.close()


def test_fail_retries_then_dead_letters(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings", lambda: _settings_with(whatsapp_job_max_attempts=2)
    )
    q.enqueue(db_session, "outbound_send", {})
    j = q.claim_next(db_session)
    q.fail(db_session, j, "boom")
    assert db_session.get(WhatsAppJob, j.id).status == "pending"
    j = q.claim_next(db_session)
    q.fail(db_session, j, "boom again")
    assert db_session.get(WhatsAppJob, j.id).status == "dead_letter"


def test_fail_recovers_from_aborted_transaction(db_session, monkeypatch):
    # Simulate Phase B's worker: the handler touched the DB badly and raised,
    # leaving the session's transaction aborted. `fail` must still transition
    # the job and never leave it stuck in `processing`.
    monkeypatch.setattr(
        "app.config.get_settings", lambda: _settings_with(whatsapp_job_max_attempts=5)
    )
    q.enqueue(db_session, "inbound_message", {"x": 1})
    j = q.claim_next(db_session)
    job_id = j.id

    try:
        db_session.execute(text("SELECT * FROM no_such_table"))
    except Exception:
        pass  # transaction is now aborted

    q.fail(db_session, j, "boom")  # must not raise

    db_session.rollback()
    row = db_session.get(WhatsAppJob, job_id)
    assert row.status == "pending"
    assert row.last_error == "boom"


def test_fail_dead_letters_from_aborted_transaction(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings", lambda: _settings_with(whatsapp_job_max_attempts=1)
    )
    q.enqueue(db_session, "outbound_send", {})
    j = q.claim_next(db_session)
    job_id = j.id
    try:
        db_session.execute(text("SELECT * FROM no_such_table"))
    except Exception:
        pass
    q.fail(db_session, j, "kaboom")
    db_session.rollback()
    assert db_session.get(WhatsAppJob, job_id).status == "dead_letter"


def test_enqueue_derives_business_id_from_payload(db_session):
    from app.models import Business

    biz = Business(name="Acme")
    db_session.add(biz)
    db_session.commit()

    job = q.enqueue(
        db_session, "outbound_send", {"business_id": str(biz.id), "kind": "text"}
    )
    row = db_session.get(WhatsAppJob, job.id)
    assert row.business_id == biz.id


def test_complete_marks_done(db_session):
    q.enqueue(db_session, "inbound_message", {})
    j = q.claim_next(db_session)
    q.complete(db_session, j)
    row = db_session.get(WhatsAppJob, j.id)
    assert row.status == "done" and row.processed_at is not None


def test_dead_letter_posts_webhook(db_session, monkeypatch):
    posts = []

    def fake_post(url, json=None, timeout=None):
        posts.append({"url": url, "json": json, "timeout": timeout})
        raise RuntimeError("webhook down")  # failure must be swallowed

    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: _settings_with(
            whatsapp_job_max_attempts=1,
            deadletter_webhook_url="https://hook.example/dl",
        ),
    )
    monkeypatch.setattr("app.services.whatsapp_jobs.httpx.post", fake_post)

    bid = uuid.uuid4()
    q.enqueue(db_session, "outbound_send", {"m": 1})
    j = q.claim_next(db_session)
    q.fail(db_session, j, "kaboom")  # must not raise despite webhook error

    assert db_session.get(WhatsAppJob, j.id).status == "dead_letter"
    assert len(posts) == 1
    assert posts[0]["url"] == "https://hook.example/dl"
    assert posts[0]["timeout"] == 5
    assert posts[0]["json"]["id"] == str(j.id)


def test_dead_letter_inbound_enqueues_owner_reply(db_session, monkeypatch):
    """I5: an inbound_message that dead-letters (Claude outage, malformed tool
    response) must enqueue a text outbound_send telling the owner, in the same
    transaction. An outbound_send dead-lettering must NOT (no reply loop)."""
    from app.models import Business

    monkeypatch.setattr(
        "app.config.get_settings", lambda: _settings_with(whatsapp_job_max_attempts=1)
    )
    biz = Business(name="Acme")
    db_session.add(biz)
    db_session.commit()

    q.enqueue(
        db_session,
        "inbound_message",
        {"business_id": str(biz.id), "sender": "+919000000001", "text": "invoice ..."},
    )
    j = q.claim_next(db_session)
    q.fail(db_session, j, "Claude API error: 529 overloaded")

    replies = (
        db_session.query(WhatsAppJob)
        .filter_by(type="outbound_send", business_id=biz.id)
        .all()
    )
    assert len(replies) == 1
    assert replies[0].payload["kind"] == "text"
    assert replies[0].payload["to"] == "+919000000001"
    assert "web app" in replies[0].payload["body"].lower()

    # an outbound_send dead-lettering spawns nothing
    q.enqueue(db_session, "outbound_send", {"business_id": str(biz.id), "kind": "text"})
    j2 = q.claim_next(db_session)
    q.fail(db_session, j2, "meta down")
    assert (
        db_session.query(WhatsAppJob).filter_by(type="outbound_send").count() == 2
    )  # the one we just enqueued + the I5 reply; no third


def test_webhook_last_error_truncated_to_200(db_session, monkeypatch):
    """M4: the third-party dead-letter webhook gets last_error truncated to 200
    chars (model-derived content, DPDP); the DB column keeps the full string."""
    posts = []
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: _settings_with(
            whatsapp_job_max_attempts=1, deadletter_webhook_url="https://hook.example/dl"
        ),
    )
    monkeypatch.setattr(
        "app.services.whatsapp_jobs.httpx.post",
        lambda url, json=None, timeout=None: posts.append(json),
    )

    long_err = "x" * 500
    q.enqueue(db_session, "outbound_send", {"m": 1})
    j = q.claim_next(db_session)
    q.fail(db_session, j, long_err)

    assert len(posts[0]["last_error"]) == 200
    assert db_session.get(WhatsAppJob, j.id).last_error == long_err  # full in DB
