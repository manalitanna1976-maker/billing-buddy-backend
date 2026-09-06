"""Task B6: Phase A + B end-to-end.

Signed webhook (text dictation) -> worker drains the queue -> an interactive
`buttons` confirm prompt goes out. Then a signed webhook (Confirm button tap)
-> worker drains -> exactly one Invoice row + the rendered PDF bytes reach the
(mocked) Meta media upload.

Only the two true externals are mocked: the Claude parser (`parse_message`) and
the Meta adapter (`whatsapp_client.*` + `pdf.render_invoice_pdf`). Everything in
between -- webhook auth, dedup, rate limit, job queue, conversation state
machine, deterministic customer resolution, invoice creation, numbering -- runs
for real.
"""

import hashlib
import hmac
import json
from decimal import Decimal

from app.config import get_settings
from app.models import (
    Business,
    Customer,
    Invoice,
    WhatsAppAuthorizedSender,
    WhatsAppConnection,
    WhatsAppConversation,
)
from app.security_crypto import encrypt_secret
from app.services import pdf as pdf_service
from app.services import whatsapp_client
from app.services import whatsapp_flow as flow
from app.services.invoice_ai_parser import ProposedDraft, ProposedLine
from app.workers import whatsapp_worker as worker

SENDER = "+911234567890"


def _sig(body: bytes) -> str:
    mac = hmac.new(get_settings().whatsapp_app_secret.encode(), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _post(client, body: dict):
    raw = json.dumps(body).encode()
    return client.post(
        "/whatsapp/webhook",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sig(raw)},
    )


def _webhook_body(*, text=None, button_id=None, mid):
    message = {"id": mid, "from": SENDER}
    if button_id is not None:
        message["type"] = "button"
        message["button"] = {"payload": button_id, "text": "Confirm"}
    else:
        message["type"] = "text"
        message["text"] = {"body": text}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba-1",
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "pn1"},
                            "messages": [message],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _drain(db):
    for _ in range(50):
        if not worker.run_once(db):
            return
    raise AssertionError("worker did not drain the queue")


def test_phase_a_plus_b_end_to_end(client, db_session, monkeypatch):
    b = Business(name="Acme Corp", state="Gujarat")
    db_session.add(b)
    db_session.flush()
    db_session.add(
        WhatsAppConnection(
            business_id=b.id,
            phone_number_id="pn1",
            waba_id="waba-1",
            access_token_encrypted=encrypt_secret("EAA-live-token"),
            status="active",
        )
    )
    db_session.add(
        WhatsAppAuthorizedSender(
            business_id=b.id, phone_e164=SENDER, enrolled_by="owner@acme.test"
        )
    )
    db_session.add(
        Customer(business_id=b.id, name="Rajesh Traders", place_of_supply="Gujarat")
    )
    db_session.commit()

    # --- external mocks ---------------------------------------------------- #
    monkeypatch.setattr(
        flow,
        "parse_message",
        lambda text, prior: ProposedDraft(
            customer_name="Rajesh Traders",
            line_items=[ProposedLine("Widget", Decimal("2"), Decimal("100"), Decimal("18"))],
            gaps=[],
        ),
    )

    sends: list[tuple] = []
    monkeypatch.setattr(
        whatsapp_client, "send_text",
        lambda conn, to, body: sends.append(("text", to, body)) or "wamid.s-text",
    )
    monkeypatch.setattr(
        whatsapp_client, "send_buttons",
        lambda conn, to, body, buttons: sends.append(("buttons", to, body, buttons))
        or "wamid.s-btn",
    )
    uploaded: list[bytes] = []
    monkeypatch.setattr(
        whatsapp_client, "upload_media",
        lambda conn, content, filename, mime: uploaded.append(content) or "media-1",
    )
    monkeypatch.setattr(
        whatsapp_client, "send_document",
        lambda conn, to, media_id, filename, caption=None: sends.append(
            ("document", to, media_id, filename)
        )
        or "wamid.s-doc",
    )
    monkeypatch.setattr(pdf_service, "render_invoice_pdf", lambda invoice: b"%PDF-1.4 fake")

    # --- 1. inbound dictation ------------------------------------------------ #
    assert _post(client, _webhook_body(text="invoice rajesh 2 widgets 100 18% gst", mid="wamid.e2e-1")).status_code == 200
    _drain(db_session)

    db_session.expire_all()
    conv = db_session.query(WhatsAppConversation).one()
    assert conv.state == "awaiting_confirm"
    assert [s for s in sends if s[0] == "buttons"], sends
    assert db_session.query(Invoice).count() == 0

    # --- 2. Confirm tap ---------------------------------------------------- #
    assert _post(client, _webhook_body(button_id="wa_confirm", mid="wamid.e2e-2")).status_code == 200
    _drain(db_session)

    db_session.expire_all()
    invoices = db_session.query(Invoice).all()
    assert len(invoices) == 1
    assert invoices[0].invoice_no == "1"

    assert uploaded == [b"%PDF-1.4 fake"]
    assert [s for s in sends if s[0] == "document"], sends
