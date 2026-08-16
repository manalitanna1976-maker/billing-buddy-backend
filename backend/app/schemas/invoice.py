import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InvoiceLineItemInput(BaseModel):
    product_name: str
    hsn_sac: str | None = None
    qty: Decimal
    uom: str | None = None
    price: Decimal
    discount: Decimal = Decimal("0")
    gst_rate: Decimal = Decimal("0")


class InvoiceLineItemRead(InvoiceLineItemInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sr_no: int
    line_total: Decimal


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_type: str | None = None
    invoice_date: date
    challan_no: str | None = None
    challan_date: date | None = None
    po_no: str | None = None
    po_date: date | None = None
    lr_no: str | None = None
    eway_no: str | None = None
    delivery_mode: str | None = None
    due_date: date | None = None
    bank_account_id: uuid.UUID | None = None
    discount_type: str = "Rs"
    discount_value: Decimal = Decimal("0")
    tcs: Decimal = Decimal("0")
    round_off: bool = True
    terms_title: str | None = None
    terms_detail: str | None = None
    notes: str | None = None
    remarks: str | None = None
    payment_type: str = "credit"
    line_items: list[InvoiceLineItemInput]


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    invoice_type: str | None
    invoice_date: date
    customer_id: uuid.UUID
    challan_no: str | None
    challan_date: date | None
    po_no: str | None
    po_date: date | None
    lr_no: str | None
    eway_no: str | None
    delivery_mode: str | None
    due_date: date | None
    bank_account_id: uuid.UUID | None
    discount_type: str
    discount_value: Decimal
    tcs: Decimal
    round_off: bool
    terms_title: str | None
    terms_detail: str | None
    notes: str | None
    remarks: str | None
    taxable_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    payment_type: str
    status: str
    line_items: list[InvoiceLineItemRead]


class InvoiceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    invoice_date: date
    grand_total: Decimal
    status: str
