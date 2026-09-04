import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Customer, Invoice
from app.schemas.invoice import InvoiceCreate, InvoiceListItem, InvoiceRead
from app.services.invoices import apply_totals_and_items, create_invoice_for_business
from app.services.pdf import render_invoice_pdf

router = APIRouter(prefix="/invoices", tags=["invoices"])

_HEADER_CONTROL_CHARS = re.compile(r'[\r\n\x00-\x1f\x7f]')


def _safe_pdf_filename(invoice_no: str) -> str:
    """Sanitize invoice_no for embedding in a Content-Disposition header.

    invoice_no is `{business.invoice_prefix}{seq}{business.invoice_postfix}`
    (see app/services/numbering.py) and business.invoice_prefix/postfix are
    free-text fields a business owner can set to arbitrary strings via
    PUT /business — including quotes and CR/LF. Interpolating that
    unescaped directly into the header value let a crafted prefix break
    the header's quoted-string syntax, or — with an embedded \\r\\n —
    made uvicorn raise "Invalid HTTP header value" and drop the
    connection on every subsequent PDF download for that invoice. Strip
    control characters and escape backslashes/quotes for a valid
    RFC 6266 quoted-string.
    """
    stripped = _HEADER_CONTROL_CHARS.sub("", invoice_no)
    return stripped.replace("\\", "\\\\").replace('"', '\\"')


def _get_owned_or_404(db: Session, business: Business, invoice_id: uuid.UUID) -> Invoice:
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.line_items))
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if invoice is None or invoice.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    limit: int = 50,
    offset: int = 0,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    return (
        db.query(Invoice)
        .filter(Invoice.business_id == business.id)
        .order_by(Invoice.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    invoice = create_invoice_for_business(db, business, body)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, business, invoice_id)


@router.put("/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    invoice = _get_owned_or_404(db, business, invoice_id)
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    for field, value in body.model_dump(exclude={"customer_id", "line_items"}).items():
        setattr(invoice, field, value)
    invoice.customer_id = body.customer_id
    apply_totals_and_items(invoice, body, business, customer)

    db.commit()
    db.refresh(invoice)
    return invoice


@router.delete("/{invoice_id}", response_model=InvoiceRead)
def cancel_invoice(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    # Soft delete only: GST invoice numbers are sequential and legally
    # significant, so a hard delete would leave an unexplained gap with no
    # record the invoice ever existed. Cancelling preserves the row and its
    # invoice_no while marking it void.
    invoice = _get_owned_or_404(db, business, invoice_id)
    invoice.status = "cancelled"
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    invoice = _get_owned_or_404(db, business, invoice_id)
    pdf_bytes = render_invoice_pdf(invoice)
    safe_filename = _safe_pdf_filename(invoice.invoice_no)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}.pdf"'},
    )
