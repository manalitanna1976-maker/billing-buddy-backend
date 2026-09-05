"""Adapter for the official Meta WhatsApp Cloud API.

Covers the two things the webhook route needs (Task A5 wires the routes):

* inbound authenticity  -- ``verify_webhook_signature`` / ``verify_challenge``
* outbound sends         -- ``send_text`` / ``send_buttons`` / ``send_document``
                            and ``upload_media``

No retry loop lives here -- the job queue (Task A4) owns retries. Non-2xx
responses raise :class:`WhatsAppSendError`. The access token and the full
response body are never logged.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

import httpx

from app.config import get_settings

_SIG_PREFIX = "sha256="
_BODY_TRUNCATE = 500
_TIMEOUT_SECONDS = 10.0
_MAX_BUTTONS = 3


class WhatsAppSendError(RuntimeError):
    """Raised when the Cloud API returns a non-2xx response.

    Carries ``.status_code`` and a ``.body`` truncated to ~500 chars so callers
    (and the job queue) can decide whether to retry without risking that a huge
    or token-bearing payload lands in a log line.
    """

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = (body or "")[:_BODY_TRUNCATE]
        super().__init__(f"WhatsApp Cloud API returned {status_code}: {self.body}")


@dataclass
class OutboundConn:
    """Per-business connection details. ``access_token`` is already decrypted
    by the caller -- this module never touches the credential store."""

    phone_number_id: str
    access_token: str


def _client() -> httpx.Client:
    """The single seam tests patch. Returns a fresh 10s-timeout client."""

    return httpx.Client(timeout=_TIMEOUT_SECONDS)


# --------------------------------------------------------------------------- #
# inbound authenticity
# --------------------------------------------------------------------------- #
def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Constant-time check of Meta's ``X-Hub-Signature-256`` header.

    Header form is ``"sha256=<hexdigest>"``. Returns ``False`` -- never raises --
    on a missing header, a missing/other prefix, a malformed or wrong-length
    hex payload, or a digest mismatch.
    """

    if not signature_header or not signature_header.startswith(_SIG_PREFIX):
        return False
    provided = signature_header[len(_SIG_PREFIX) :]
    expected = hmac.new(
        get_settings().whatsapp_app_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if len(provided) != len(expected):
        return False
    try:
        return hmac.compare_digest(provided, expected)
    except (TypeError, ValueError):
        return False


def verify_challenge(
    mode: str | None, token: str | None, challenge: str | None
) -> str | None:
    """GET-handshake check. Echo ``challenge`` back iff ``mode == "subscribe"``
    and ``token`` matches the configured verify token (constant-time)."""

    verify_token = get_settings().whatsapp_verify_token
    # Compare as bytes: hmac.compare_digest rejects str args that contain
    # non-ASCII characters with a TypeError, and this token arrives from a
    # public, unauthenticated GET endpoint (Task A5).
    if mode == "subscribe" and hmac.compare_digest(
        (token or "").encode(), verify_token.encode()
    ):
        return challenge
    return None


# --------------------------------------------------------------------------- #
# outbound sends
# --------------------------------------------------------------------------- #
def _base(conn: OutboundConn) -> str:
    s = get_settings()
    return f"{s.whatsapp_graph_base_url}/{s.whatsapp_api_version}/{conn.phone_number_id}"


def _auth_headers(conn: OutboundConn) -> dict[str, str]:
    return {"Authorization": f"Bearer {conn.access_token}"}


def _post_message(conn: OutboundConn, payload: dict) -> str:
    with _client() as client:
        resp = client.post(
            f"{_base(conn)}/messages",
            headers=_auth_headers(conn),
            json=payload,
        )
    if resp.status_code // 100 != 2:
        raise WhatsAppSendError(resp.status_code, resp.text)
    try:
        return resp.json()["messages"][0]["id"]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise WhatsAppSendError(
            resp.status_code, f"unexpected response shape: {resp.text[:500]}"
        ) from e


def send_text(conn: OutboundConn, to_e164: str, body: str) -> str:
    """Send a plain text message. Returns the ``wa_message_id``."""

    return _post_message(
        conn,
        {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": "text",
            "text": {"body": body},
        },
    )


def send_buttons(
    conn: OutboundConn,
    to_e164: str,
    body: str,
    buttons: list[tuple[str, str]],
) -> str:
    """Send an interactive reply-button message. ``buttons`` is ``[(id, title)]``,
    max 3. Returns the ``wa_message_id``."""

    if len(buttons) > _MAX_BUTTONS:
        raise ValueError(
            f"WhatsApp interactive messages allow at most {_MAX_BUTTONS} buttons"
        )
    return _post_message(
        conn,
        {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": btn_id, "title": title}}
                        for btn_id, title in buttons
                    ]
                },
            },
        },
    )


def send_document(
    conn: OutboundConn,
    to_e164: str,
    media_id: str,
    filename: str,
    caption: str | None = None,
) -> str:
    """Send a previously uploaded document by its media id. Returns the
    ``wa_message_id``."""

    document: dict[str, str] = {"id": media_id, "filename": filename}
    if caption is not None:
        document["caption"] = caption
    return _post_message(
        conn,
        {
            "messaging_product": "whatsapp",
            "to": to_e164,
            "type": "document",
            "document": document,
        },
    )


def upload_media(
    conn: OutboundConn, content: bytes, filename: str, mime: str
) -> str:
    """Upload a file to the media endpoint and return its ``media_id``."""

    with _client() as client:
        resp = client.post(
            f"{_base(conn)}/media",
            headers=_auth_headers(conn),
            data={"messaging_product": "whatsapp", "type": mime},
            files={"file": (filename, content, mime)},
        )
    if resp.status_code // 100 != 2:
        raise WhatsAppSendError(resp.status_code, resp.text)
    try:
        return resp.json()["id"]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise WhatsAppSendError(
            resp.status_code, f"unexpected response shape: {resp.text[:500]}"
        ) from e
