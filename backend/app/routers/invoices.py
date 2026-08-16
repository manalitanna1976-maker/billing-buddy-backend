import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Customer, Invoice, InvoiceLineItem
from app.schemas.invoice import InvoiceCreate, InvoiceListItem, InvoiceRead
from app.services.gst import LineItemInput, compute_invoice_totals, line_taxable_value
from app.services.numbering import next_invoice_number

router = APIRouter(prefix="/invoices", tags=["invoices"])


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


def _apply_totals_and_items(invoice: Invoice, body: InvoiceCreate, business: Business, customer: Customer):
    same_state = bool(business.state) and business.state == customer.place_of_supply
    calc_items = [
        LineItemInput(qty=li.qty, price=li.price, discount=li.discount, gst_rate=li.gst_rate)
        for li in body.line_items
    ]
    totals = compute_invoice_totals(
        calc_items,
        same_state=same_state,
        discount_type=body.discount_type,
        discount_value=body.discount_value,
        tcs=body.tcs,
        round_off=body.round_off,
    )

    invoice.line_items.clear()
    for sr_no, (li, calc_item) in enumerate(zip(body.line_items, calc_items), start=1):
        invoice.line_items.append(
            InvoiceLineItem(
                sr_no=sr_no,
                product_name=li.product_name,
                hsn_sac=li.hsn_sac,
                qty=li.qty,
                uom=li.uom,
                price=li.price,
                discount=li.discount,
                gst_rate=li.gst_rate,
                line_total=line_taxable_value(calc_item),
            )
        )

    invoice.taxable_total = totals.taxable_total
    invoice.tax_total = totals.tax_total
    invoice.grand_total = totals.grand_total


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
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    invoice = Invoice(
        business_id=business.id,
        customer_id=body.customer_id,
        invoice_no=next_invoice_number(db, business),
        **body.model_dump(exclude={"customer_id", "line_items"}),
    )
    _apply_totals_and_items(invoice, body, business, customer)

    db.add(invoice)
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
    _apply_totals_and_items(invoice, body, business, customer)

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
