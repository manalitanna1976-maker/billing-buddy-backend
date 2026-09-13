import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.validators import clean_optional_text


class PurchaseLineItemInput(BaseModel):
    product_id: uuid.UUID | None = None
    product_name: str | None = None
    hsn_sac: str | None = None
    qty: Decimal = Field(gt=0, le=Decimal("1000000"))
    uom: str | None = None
    price: Decimal = Field(ge=0, le=Decimal("100000000"))
    discount: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    gst_rate: Decimal = Field(default=Decimal("0"), ge=0, le=28)

    @field_validator("product_name", "hsn_sac", "uom")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @model_validator(mode="after")
    def _product_reference_required(self) -> "PurchaseLineItemInput":
        if self.product_id is None and not self.product_name:
            raise ValueError("line item must set product_id or product_name")
        return self


class PurchaseLineItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sr_no: int
    product_id: uuid.UUID | None
    raw_description: str
    hsn_sac: str | None
    qty: Decimal
    uom: str | None
    price: Decimal
    discount: Decimal
    gst_rate: Decimal
    line_total: Decimal


class PurchaseCreate(BaseModel):
    supplier_id: uuid.UUID
    invoice_no: str | None = None
    invoice_date: date | None = None
    po_no: str | None = None
    shipping_total: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    other_charges: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    round_off: Decimal = Field(default=Decimal("0"), ge=Decimal("-1000"), le=Decimal("1000"))
    notes: str | None = None
    line_items: list[PurchaseLineItemInput] = Field(min_length=1)

    @field_validator("invoice_no", "po_no", "notes")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)


class PurchaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_id: uuid.UUID | None
    invoice_no: str | None
    invoice_date: date | None
    po_no: str | None
    taxable_total: Decimal
    tax_total: Decimal
    shipping_total: Decimal
    other_charges: Decimal
    round_off: Decimal
    grand_total: Decimal
    currency: str
    notes: str | None
    origin: str
    status: str
    doc_type: str
    line_items: list[PurchaseLineItemRead]


class PurchaseListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str | None
    po_no: str | None
    invoice_date: date | None
    supplier_name: str | None = None
    grand_total: Decimal
    status: str
    origin: str
