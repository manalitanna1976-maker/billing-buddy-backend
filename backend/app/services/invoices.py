import uuid

from sqlalchemy.orm import Session

from app.constants.indian_states import same_gst_state
from app.models import BankAccount, Business, Customer, Invoice, InvoiceLineItem
from app.schemas.invoice import InvoiceCreate
from app.services.gst import LineItemInput, compute_invoice_totals, line_taxable_value
from app.services.numbering import next_invoice_number


class CustomerNotFoundError(Exception):
    """Raised by _resolve_customer / create_invoice_for_business when the
    referenced customer does not exist or does not belong to the business.

    Domain-level so non-HTTP callers (e.g. the WhatsApp worker) can handle it
    without depending on FastAPI. The web route translates it to HTTP 404.
    """


class BankAccountNotFoundError(Exception):
    """Raised when the invoice references a bank account that does not exist
    or does not belong to the business. Router translates to HTTP 404."""


class InvoiceLockedError(Exception):
    """Raised when a caller tries to edit or cancel an invoice that is no
    longer a draft (finalized or already cancelled). Router -> HTTP 409."""


def snapshot_bill_to(invoice: Invoice, customer: Customer) -> None:
    """Freeze the customer's details onto the invoice as of now. A GST invoice
    is a legal record; editing the customer master later must not rewrite it."""
    invoice.bill_to_name = customer.name
    invoice.bill_to_address = customer.address
    invoice.bill_to_gstin = customer.gstin
    invoice.bill_to_pan = customer.pan
    invoice.bill_to_state = customer.place_of_supply
    invoice.bill_to_phone = customer.phone
    invoice.ship_to = customer.ship_to


def apply_totals_and_items(
    invoice: Invoice, body: InvoiceCreate, business: Business, customer: Customer
) -> None:
    # Tolerant intra/inter-state detection: "Maharashtra" and "27-Maharashtra"
    # are the same state. See app/constants/indian_states.py.
    same_state = same_gst_state(business.state, customer.place_of_supply)

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
    invoice.discount_amount = totals.discount_amount
    invoice.cgst_total = totals.cgst_total
    invoice.sgst_total = totals.sgst_total
    invoice.igst_total = totals.igst_total
    invoice.tax_total = totals.tax_total
    invoice.round_off_amount = totals.round_off_amount
    invoice.grand_total = totals.grand_total


def _resolve_customer(db: Session, business: Business, customer_id: uuid.UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.business_id != business.id:
        raise CustomerNotFoundError("Customer not found")
    return customer


def _resolve_bank_account(
    db: Session, business: Business, bank_account_id: uuid.UUID | None
) -> None:
    if bank_account_id is None:
        return
    account = db.get(BankAccount, bank_account_id)
    if account is None or account.business_id != business.id:
        raise BankAccountNotFoundError("Bank account not found")


def create_invoice_for_business(db: Session, business: Business, body: InvoiceCreate) -> Invoice:
    """Build and persist (flush, not commit) an invoice for `business`.

    Does not commit -- the caller owns the transaction boundary (commit on
    success, rollback on failure). Note it also mutates business.next_invoice_seq
    via next_invoice_number(), so a caller that swallows an exception and reuses
    the session carries a phantom sequence increment.
    """
    customer = _resolve_customer(db, business, body.customer_id)
    _resolve_bank_account(db, business, body.bank_account_id)
    invoice = Invoice(
        business_id=business.id,
        customer_id=body.customer_id,
        invoice_no=next_invoice_number(db, business),
        **body.model_dump(exclude={"customer_id", "line_items"}),
    )
    snapshot_bill_to(invoice, customer)
    apply_totals_and_items(invoice, body, business, customer)
    db.add(invoice)
    db.flush()
    return invoice
