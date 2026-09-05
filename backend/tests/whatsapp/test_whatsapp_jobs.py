import uuid

import pytest

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
