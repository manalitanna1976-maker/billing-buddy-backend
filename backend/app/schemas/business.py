import uuid

from pydantic import BaseModel, ConfigDict


class BusinessUpdate(BaseModel):
    name: str | None = None
    gstin: str | None = None
    address: str | None = None
    state: str | None = None
    phone: str | None = None
    email: str | None = None
    invoice_prefix: str | None = None
    invoice_postfix: str | None = None


class BusinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    gstin: str | None
    address: str | None
    state: str | None
    phone: str | None
    email: str | None
    logo_url: str | None
    signature_url: str | None
    invoice_prefix: str
    invoice_postfix: str
