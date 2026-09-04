import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Business, Customer, Invoice, InvoiceLineItem
from app.schemas.invoice import InvoiceCreate
from app.services.gst import LineItemInput, compute_invoice_totals, line_taxable_value
from app.services.numbering import next_invoice_number


def apply_totals_and_items(invoice: Invoice, body: InvoiceCreate, business: Business, customer: Customer) -> None:
    # Both `Business.state` and `Customer.place_of_supply` are free-text
    # fields (no fixed dropdown of Indian states), so compare case/whitespace
    # insensitively — "Gujarat" vs "gujarat" is the same state for GST
    # purposes and must produce CGST+SGST, not silently fall through to IGST.
    same_state = bool(business.state) and bool(customer.place_of_supply) and (
        business.state.strip().casefold() == customer.place_of_supply.strip().casefold()
    )
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


def _resolve_customer(db: Session, business: Business, customer_id: uuid.UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


def create_invoice_for_business(db: Session, business: Business, body: InvoiceCreate) -> Invoice:
    """Build and persist (flush, not commit) an invoice for `business`.

    Does not commit -- the caller owns the transaction boundary (commit on
    success, rollback on failure). Note it also mutates business.next_invoice_seq
    via next_invoice_number(), so a caller that swallows an exception and reuses
    the session carries a phantom sequence increment.
    """
    customer = _resolve_customer(db, business, body.customer_id)
    invoice = Invoice(
        business_id=business.id,
        customer_id=body.customer_id,
        invoice_no=next_invoice_number(db, business),
        **body.model_dump(exclude={"customer_id", "line_items"}),
    )
    apply_totals_and_items(invoice, body, business, customer)
    db.add(invoice)
    db.flush()
    # No db.refresh() here: Invoice has no server-side column defaults, so
    # flush() already populates the instance, and the caller commits (which
    # re-expires everything) then refreshes if it needs post-commit state.
    return invoice
