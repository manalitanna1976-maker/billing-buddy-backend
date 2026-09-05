import hashlib
import hmac
import json

import httpx
import pytest

from app.config import get_settings
from app.services import whatsapp_client
from app.services.whatsapp_client import (
    OutboundConn,
    WhatsAppSendError,
    send_buttons,
    send_document,
    send_text,
    upload_media,
    verify_challenge,
    verify_webhook_signature,
)


def _sig(body: bytes) -> str:
    mac = hmac.new(get_settings().whatsapp_app_secret.encode(), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _mock_client(monkeypatch, handler):
    """Patch the single ``_client()`` seam so outbound calls hit a MockTransport."""

    def factory(*a, **k):
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(whatsapp_client, "_client", factory)


# --------------------------------------------------------------------------- #
# signature verification
# --------------------------------------------------------------------------- #
def test_signature_valid():
    body = b'{"a":1}'
    assert verify_webhook_signature(body, _sig(body)) is True


def test_signature_tampered_digest():
    body = b'{"a":1}'
    assert verify_webhook_signature(body, "sha256=deadbeef") is False


def test_signature_none_header():
    assert verify_webhook_signature(b'{"a":1}', None) is False


def test_signature_no_prefix():
    assert verify_webhook_signature(b'{"a":1}', "garbage") is False


def test_signature_correct_prefix_wrong_length_hex():
    body = b'{"a":1}'
    assert verify_webhook_signature(body, "sha256=abcd") is False


def test_signature_correct_prefix_wrong_but_full_length_hex():
    body = b'{"a":1}'
    good = _sig(body)[len("sha256=") :]
    flipped = ("0" if good[0] != "0" else "1") + good[1:]
    assert verify_webhook_signature(body, "sha256=" + flipped) is False


def test_signature_wrong_body():
    assert verify_webhook_signature(b'{"a":2}', _sig(b'{"a":1}')) is False


def test_signature_non_hex_full_length():
    body = b'{"a":1}'
    assert verify_webhook_signature(body, "sha256=" + "z" * 64) is False


def test_signature_non_ascii_full_length_header():
    # Exercises the ``except (TypeError, ValueError)`` guard: compare_digest
    # rejects non-ASCII str args.
    assert verify_webhook_signature(b"x", "sha256=" + "ñ" * 64) is False


# --------------------------------------------------------------------------- #
# GET challenge
# --------------------------------------------------------------------------- #
def test_challenge_ok():
    t = get_settings().whatsapp_verify_token
    assert verify_challenge("subscribe", t, "1234") == "1234"


def test_challenge_wrong_token():
    assert verify_challenge("subscribe", "wrong", "1234") is None


def test_challenge_wrong_mode():
    t = get_settings().whatsapp_verify_token
    assert verify_challenge("unsubscribe", t, "1234") is None


def test_challenge_none_token():
    assert verify_challenge("subscribe", None, "1234") is None


def test_challenge_non_ascii_token_returns_none():
    assert verify_challenge("subscribe", "ñ", "x") is None


# --------------------------------------------------------------------------- #
# outbound send
# --------------------------------------------------------------------------- #
def test_send_text_posts_to_graph(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]})

    _mock_client(monkeypatch, handler)
    mid = send_text(OutboundConn("PN123", "tok-abc"), "+9199", "hi")
    assert mid == "wamid.OUT"
    s = get_settings()
    assert seen["url"] == f"{s.whatsapp_graph_base_url}/{s.whatsapp_api_version}/PN123/messages"
    assert seen["auth"] == "Bearer tok-abc"
    assert seen["json"] == {
        "messaging_product": "whatsapp",
        "to": "+9199",
        "type": "text",
        "text": {"body": "hi"},
    }


def test_send_buttons_payload_shape(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.B"}]})

    _mock_client(monkeypatch, handler)
    mid = send_buttons(
        OutboundConn("PN", "t"),
        "+9199",
        "Pick one",
        [("confirm", "Confirm"), ("edit", "Edit")],
    )
    assert mid == "wamid.B"
    body = seen["json"]
    assert body["type"] == "interactive"
    assert body["interactive"]["type"] == "button"
    assert body["interactive"]["body"] == {"text": "Pick one"}
    assert body["interactive"]["action"]["buttons"] == [
        {"type": "reply", "reply": {"id": "confirm", "title": "Confirm"}},
        {"type": "reply", "reply": {"id": "edit", "title": "Edit"}},
    ]


def test_send_buttons_rejects_more_than_three(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(200, json={"messages": [{"id": "x"}]}))
    with pytest.raises(ValueError):
        send_buttons(
            OutboundConn("PN", "t"),
            "+9199",
            "too many",
            [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        )


def test_send_document_payload_shape(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.D"}]})

    _mock_client(monkeypatch, handler)
    mid = send_document(OutboundConn("PN", "t"), "+9199", "MID1", "invoice.pdf", "Your invoice")
    assert mid == "wamid.D"
    assert seen["json"]["type"] == "document"
    assert seen["json"]["document"] == {
        "id": "MID1",
        "filename": "invoice.pdf",
        "caption": "Your invoice",
    }


def test_send_document_omits_caption_when_none(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.D"}]})

    _mock_client(monkeypatch, handler)
    send_document(OutboundConn("PN", "t"), "+9199", "MID1", "invoice.pdf")
    assert "caption" not in seen["json"]["document"]


def test_upload_media_multipart(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"id": "MEDIA-123"})

    _mock_client(monkeypatch, handler)
    media_id = upload_media(OutboundConn("PN9", "tok9"), b"%PDF-1.4 data", "invoice.pdf", "application/pdf")
    assert media_id == "MEDIA-123"
    s = get_settings()
    assert seen["url"] == f"{s.whatsapp_graph_base_url}/{s.whatsapp_api_version}/PN9/media"
    assert seen["auth"] == "Bearer tok9"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"whatsapp" in seen["body"]
    assert b"%PDF-1.4 data" in seen["body"]
    assert b"invoice.pdf" in seen["body"]
    assert b"application/pdf" in seen["body"]  # required `type` form field


def test_send_raises_on_non_2xx(monkeypatch):
    _mock_client(
        monkeypatch,
        lambda r: httpx.Response(400, json={"error": {"message": "bad"}}),
    )
    with pytest.raises(WhatsAppSendError) as exc:
        send_text(OutboundConn("PN", "t"), "+9199", "x")
    assert exc.value.status_code == 400
    assert "bad" in exc.value.body


def test_send_error_truncates_body(monkeypatch):
    huge = "e" * 5000
    _mock_client(monkeypatch, lambda r: httpx.Response(500, text=huge))
    with pytest.raises(WhatsAppSendError) as exc:
        send_text(OutboundConn("PN", "t"), "+9199", "x")
    assert len(exc.value.body) <= 500


def test_upload_media_raises_on_non_2xx(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(401, json={"error": {"message": "no"}}))
    with pytest.raises(WhatsAppSendError):
        upload_media(OutboundConn("PN", "t"), b"x", "f.pdf", "application/pdf")


def test_send_text_unexpected_2xx_shape_raises_send_error(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(WhatsAppSendError) as exc:
        send_text(OutboundConn("PN", "t"), "+9199", "x")
    assert "unexpected response shape" in exc.value.body


def test_upload_media_unexpected_2xx_shape_raises_send_error(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(WhatsAppSendError):
        upload_media(OutboundConn("PN", "t"), b"x", "f.pdf", "application/pdf")


def test_send_error_message_has_no_token(monkeypatch):
    _mock_client(monkeypatch, lambda r: httpx.Response(400, text="oops"))
    with pytest.raises(WhatsAppSendError) as exc:
        send_text(OutboundConn("PN", "super-secret-token"), "+9199", "x")
    assert "super-secret-token" not in str(exc.value)
