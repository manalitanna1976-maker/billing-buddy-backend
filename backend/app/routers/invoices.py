import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import get_current_business
from app.models import BankAccount, Business, Customer, Invoice
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceRead,
)
from app.services.invoices import (
    BankAccountNotFoundError,
    CustomerNotFoundError,
    apply_totals_and_items,
    create_invoice_for_business,
    snapshot_bill_to,
)
from app.services.pdf import render_invoice_pdf
from app.time_utils import utcnow

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


@router.get("", response_model=InvoiceListResponse)
def list_invoices(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = None,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    # Single query with the customer name joined in -- the list page no longer
    # needs an N+1 fan-out of GET /invoices/{id} just to show the customer.
    base = (
        select(Invoice, Customer.name.label("customer_name"))
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(Invoice.business_id == business.id)
    )
    if status_filter:
        base = base.where(Invoice.status == status_filter)
    if q:
        like = f"%{q}%"
        base = base.where(Invoice.invoice_no.ilike(like) | Customer.name.ilike(like))

    total = db.execute(
        select(func.count()).select_from(base.order_by(None).subquery())
    ).scalar_one()

    rows = db.execute(
        base.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    ).all()

    items = [
        {
            "id": inv.id,
            "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date,
            "customer_name": customer_name,
            "grand_total": inv.grand_total,
            "status": inv.status,
        }
        for inv, customer_name in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    try:
        invoice = create_invoice_for_business(db, business, body)
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        ) from None
    except BankAccountNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
        ) from None
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
    if invoice.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a {invoice.status} invoice cannot be edited",
        )
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    if body.bank_account_id is not None:
        account = db.get(BankAccount, body.bank_account_id)
        if account is None or account.business_id != business.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found"
            )

    for field, value in body.model_dump(exclude={"customer_id", "line_items"}).items():
        setattr(invoice, field, value)
    invoice.customer_id = body.customer_id
    snapshot_bill_to(invoice, customer)
    apply_totals_and_items(invoice, body, business, customer)

    db.commit()
    db.refresh(invoice)
    return invoice


@router.post("/{invoice_id}/finalize", response_model=InvoiceRead)
def finalize_invoice(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    """draft -> saved. A finalized invoice is locked: no further edits, only
    cancellation. This is the point the invoice becomes a committed record."""
    invoice = _get_owned_or_404(db, business, invoice_id)
    if invoice.status == "saved":
        return invoice
    if invoice.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a {invoice.status} invoice cannot be finalized",
        )
    if not invoice.line_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot finalize an invoice with no line items",
        )
    invoice.status = "saved"
    invoice.finalized_at = utcnow()
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
    if invoice.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="invoice is already cancelled"
        )
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
