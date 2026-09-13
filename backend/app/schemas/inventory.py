import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.validators import clean_optional_text, require_non_empty


class ProductCreate(BaseModel):
    name: str
    hsn_sac: str | None = None
    uom: str | None = None
    reorder_level: Decimal | None = Field(default=None, ge=0)
    default_purchase_price: Decimal | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return require_non_empty(v)

    @field_validator("hsn_sac", "uom")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)


class ProductUpdate(BaseModel):
    name: str | None = None
    hsn_sac: str | None = None
    uom: str | None = None
    reorder_level: Decimal | None = Field(default=None, ge=0)
    default_purchase_price: Decimal | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else require_non_empty(v)

    @field_validator("hsn_sac", "uom")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    hsn_sac: str | None
    uom: str | None
    current_qty: Decimal
    reorder_level: Decimal | None
    default_purchase_price: Decimal | None
    auto_created: bool
    needs_review: bool


class StockAdjustment(BaseModel):
    delta_qty: Decimal
    note: str | None = None

    @field_validator("delta_qty")
    @classmethod
    def _nonzero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("delta_qty must not be zero")
        return v

    @field_validator("note")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    delta_qty: Decimal
    balance_after: Decimal
    reason: str
    ref_type: str | None
    ref_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class SupplierCreate(BaseModel):
    name: str
    gstin: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    state_code: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return require_non_empty(v)

    @field_validator("phone", "email", "address", "state_code")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        cleaned = clean_optional_text(v)
        return cleaned.upper() if cleaned else cleaned


class SupplierUpdate(BaseModel):
    name: str | None = None
    gstin: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    state_code: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else require_non_empty(v)

    @field_validator("phone", "email", "address", "state_code")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        cleaned = clean_optional_text(v)
        return cleaned.upper() if cleaned else cleaned


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    gstin: str | None
    phone: str | None
    email: str | None
    address: str | None
    state_code: str | None
