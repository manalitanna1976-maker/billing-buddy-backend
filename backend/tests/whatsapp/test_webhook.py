import hashlib
import hmac
import json

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Business,
    WhatsAppAuthorizedSender,
    WhatsAppConnection,
    WhatsAppJob,
    WhatsAppMessageLog,
)


def _sig(body: bytes) -> str:
    mac = hmac.new(get_settings().whatsapp_app_secret.encode(), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def post(client, body: dict, sign: bool = True):
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Hub-Signature-256"] = _sig(raw)
    return client.post("/whatsapp/webhook", content=raw, headers=headers)


def _payload(phone_number_id, frm=None, text=None, button_id=None, mid="wamid.1", statuses_only=False):
    value = {"metadata": {"phone_number_id": phone_number_id}}
    if statuses_only:
        value["statuses"] = [{"id": mid, "status": "delivered"}]
    else:
        message = {"id": mid, "from": frm}
        if button_id is not None:
            message["type"] = "button"
            message["button"] = {"payload": button_id, "text": "Confirm"}
        elif text is not None:
            message["type"] = "text"
            message["text"] = {"body": text}
        else:
            message["type"] = "text"
            message["text"] = {"body": "hello"}
        value["messages"] = [message]
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [{"value": value, "field": "messages"}],
            }
        ],
    }


def _biz(db):
    b = Business(name="Acme")
    db.add(b)
    db.flush()
    return b


def _connection(db, business_id, phone_number_id="pn1", status="active"):
    conn = WhatsAppConnection(
        business_id=business_id,
        phone_number_id=phone_number_id,
        waba_id="waba-1",
        access_token_encrypted="enc",
        status=status,
    )
    db.add(conn)
    db.flush()
    return conn


def _authorize(db, business_id, phone_e164):
    sender = WhatsAppAuthorizedSender(
        business_id=business_id, phone_e164=phone_e164, enrolled_by="owner@acme.test"
    )
    db.add(sender)
    db.flush()
    return sender


def _jobs():
    s = SessionLocal()
    try:
        return s.query(WhatsAppJob).all()
    finally:
        s.close()


def _message_logs():
    s = SessionLocal()
    try:
        return s.query(WhatsAppMessageLog).all()
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# GET challenge
# --------------------------------------------------------------------------- #
def test_get_challenge_echoes_when_token_matches(client):
    t = get_settings().whatsapp_verify_token
    resp = client.get(
        "/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": t, "hub.challenge": "1234"},
    )
    assert resp.status_code == 200
    assert resp.text == "1234"


def test_get_challenge_403_when_not(client):
    resp = client.get(
        "/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1234"},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# POST webhook
# --------------------------------------------------------------------------- #
def test_bad_signature_returns_403_and_enqueues_nothing(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    body = _payload("pn1", frm="+911234567890")
    raw = json.dumps(body).encode()
    resp = client.post(
        "/whatsapp/webhook",
        content=raw,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403
    assert _jobs() == []


def test_unknown_phone_number_id_ignored(client, db_session):
    resp = post(client, _payload("does-not-exist", frm="+911234567890"))
    assert resp.status_code == 200
    assert _jobs() == []


def test_inactive_connection_not_resolved(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id, phone_number_id="pn1", status="disconnected")
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    resp = post(client, _payload("pn1", frm="+911234567890"))
    assert resp.status_code == 200
    assert _jobs() == []


def test_unauthorized_sender_logged_no_job_no_reply(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    db_session.commit()

    resp = post(client, _payload("pn1", frm="+919999999999"))
    assert resp.status_code == 200
    assert _jobs() == []


def test_authorized_text_enqueues_inbound_message_job(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    resp = post(client, _payload("pn1", frm="+911234567890", text="Invoice for 500 to Bob", mid="wamid.text1"))
    assert resp.status_code == 200

    jobs = _jobs()
    assert len(jobs) == 1
    assert jobs[0].type == "inbound_message"
    assert jobs[0].payload["kind"] == "text"
    assert jobs[0].payload["text"] == "Invoice for 500 to Bob"
    assert jobs[0].payload["sender"] == "+911234567890"
    assert jobs[0].payload["wa_message_id"] == "wamid.text1"

    logs = _message_logs()
    assert len(logs) == 1
    assert logs[0].direction == "in"
    assert logs[0].wa_message_id == "wamid.text1"
    assert not hasattr(logs[0], "body")


def test_duplicate_wa_message_id_processed_once(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    payload = _payload("pn1", frm="+911234567890", text="hi", mid="wamid.dup")
    resp1 = post(client, payload)
    resp2 = post(client, payload)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(_jobs()) == 1


def test_button_reply_enqueues_button_job(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    resp = post(client, _payload("pn1", frm="+911234567890", button_id="confirm", mid="wamid.btn1"))
    assert resp.status_code == 200

    jobs = _jobs()
    assert len(jobs) == 1
    assert jobs[0].type == "inbound_message"
    assert jobs[0].payload["kind"] == "button"
    assert jobs[0].payload["button_id"] == "confirm"


def test_oversize_text_enqueues_outbound_not_inbound(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    max_bytes = get_settings().whatsapp_message_max_bytes
    huge_text = "x" * (max_bytes + 1)
    resp = post(client, _payload("pn1", frm="+911234567890", text=huge_text, mid="wamid.huge"))
    assert resp.status_code == 200

    jobs = _jobs()
    assert len(jobs) == 1
    assert jobs[0].type == "outbound_send"
    assert jobs[0].payload["kind"] == "text"
    assert jobs[0].payload["to"] == "+911234567890"


def test_status_only_payload_acked_and_ignored(client, db_session):
    resp = post(client, _payload("pn1", statuses_only=True))
    assert resp.status_code == 200
    assert _jobs() == []


def test_oversize_request_body_rejected_413_enqueues_nothing(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    body = _payload("pn1", frm="+911234567890", text="x" * 600_000, mid="wamid.big")
    raw = json.dumps(body).encode()
    resp = client.post(
        "/whatsapp/webhook",
        content=raw,
        headers={"X-Hub-Signature-256": _sig(raw), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert _jobs() == []


def test_empty_text_body_enqueues_nothing(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    resp = post(client, _payload("pn1", frm="+911234567890", text="   ", mid="wamid.empty"))
    assert resp.status_code == 200
    assert _jobs() == []


def test_per_business_rate_limit_blocks_after_cap(client, db_session, monkeypatch):
    from app import config as _config

    lowered = _config.Settings(
        **{
            **_config.get_settings().model_dump(),
            "whatsapp_rate_per_business": 3,
            "whatsapp_rate_per_sender": 100,
        }
    )
    monkeypatch.setattr("app.routers.whatsapp.get_settings", lambda: lowered)

    b = _biz(db_session)
    _connection(db_session, b.id)
    senders = [f"+9112345678{i:02d}" for i in range(5)]
    for s in senders:
        _authorize(db_session, b.id, s)
    db_session.commit()

    for i, s in enumerate(senders[:3]):
        resp = post(client, _payload("pn1", frm=s, text=f"msg {i}", mid=f"wamid.b{i}"))
        assert resp.status_code == 200
    assert len(_jobs()) == 3

    # A distinct sender (well under the per-sender cap) is still blocked once
    # the shared per-business bucket is full.
    resp = post(client, _payload("pn1", frm=senders[3], text="over", mid="wamid.bover"))
    assert resp.status_code == 200
    assert len(_jobs()) == 3


def test_per_sender_rate_limit_blocks_after_cap(client, db_session):
    b = _biz(db_session)
    _connection(db_session, b.id)
    _authorize(db_session, b.id, "+911234567890")
    db_session.commit()

    cap = get_settings().whatsapp_rate_per_sender
    for i in range(cap):
        resp = post(client, _payload("pn1", frm="+911234567890", text=f"msg {i}", mid=f"wamid.rl{i}"))
        assert resp.status_code == 200

    assert len(_jobs()) == cap

    resp = post(client, _payload("pn1", frm="+911234567890", text="over the cap", mid="wamid.rl-over"))
    assert resp.status_code == 200
    assert len(_jobs()) == cap
