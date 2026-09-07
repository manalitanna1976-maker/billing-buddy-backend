import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validators import clean_optional_text

DiscountType = Literal["Rs", "%"]
PaymentType = Literal["credit", "cash", "cheque", "online"]
InvoiceType = Literal["Tax Invoice", "Bill of Supply", "Export Invoice"]

# An invoice may be lightly post-dated (a bill raised today for a delivery
# tomorrow) but not by months, and never before GST existed.
_MAX_FUTURE_DAYS = 30
_MIN_DATE = date(2017, 7, 1)


class InvoiceLineItemInput(BaseModel):
    product_name: str
    hsn_sac: str | None = None
    qty: Decimal = Field(gt=0, le=Decimal("1000000"))
    uom: str | None = None
    price: Decimal = Field(ge=0, le=Decimal("100000000"))
    discount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=28)

    @field_validator("product_name")
    @classmethod
    def _product_name(cls, v: str) -> str:
        trimmed = (v or "").strip()
        if not trimmed:
            raise ValueError("product name must not be blank")
        return trimmed

    @field_validator("hsn_sac", "uom")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)


class InvoiceLineItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sr_no: int
    product_name: str
    hsn_sac: str | None
    qty: Decimal
    uom: str | None
    price: Decimal
    discount: Decimal
    gst_rate: Decimal
    line_total: Decimal


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_type: InvoiceType | None = None
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
    discount_type: DiscountType = "Rs"
    discount_value: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    tcs: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000000000"))
    round_off: bool = True
    terms_title: str | None = None
    terms_detail: str | None = None
    notes: str | None = None
    remarks: str | None = None
    payment_type: PaymentType = "credit"
    line_items: list[InvoiceLineItemInput] = Field(min_length=1)

    @field_validator("invoice_date")
    @classmethod
    def _invoice_date(cls, v: date) -> date:
        if v < _MIN_DATE:
            raise ValueError(f"invoice_date cannot be before {_MIN_DATE.isoformat()}")
        if v > date.today() + timedelta(days=_MAX_FUTURE_DAYS):
            raise ValueError(f"invoice_date cannot be more than {_MAX_FUTURE_DAYS} days in the future")
        return v

    @field_validator(
        "challan_no", "po_no", "lr_no", "eway_no", "delivery_mode",
        "terms_title", "terms_detail", "notes", "remarks",
    )
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @model_validator(mode="after")
    def _percent_discount_bound(self) -> "InvoiceCreate":
        if self.discount_type == "%" and self.discount_value > 100:
            raise ValueError("a percentage discount cannot exceed 100%")
        return self


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    invoice_type: str | None
    invoice_date: date
    customer_id: uuid.UUID
    bill_to_name: str | None
    bill_to_address: str | None
    bill_to_gstin: str | None
    bill_to_pan: str | None
    bill_to_state: str | None
    bill_to_phone: str | None
    ship_to: str | None
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
    discount_amount: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    tax_total: Decimal
    round_off_amount: Decimal
    grand_total: Decimal
    payment_type: str
    status: str
    line_items: list[InvoiceLineItemRead]


class InvoiceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    invoice_date: date
    customer_name: str | None = None
    grand_total: Decimal
    status: str


class InvoiceListResponse(BaseModel):
    items: list[InvoiceListItem]
    total: int
    limit: int
    offset: int
