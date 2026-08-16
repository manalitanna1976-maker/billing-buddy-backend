import uuid

from pydantic import BaseModel, ConfigDict, Field

# max_length values mirror the column widths in app.models.Business. Without
# these, an over-length value (e.g. a pasted GSTIN with extra characters)
# reaches the DB update and raises an unhandled psycopg StringDataRightTruncation,
# surfacing as a raw 500 with no useful message instead of a normal 422.
class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    gstin: str | None = Field(default=None, max_length=15)
    address: str | None = None
    state: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=200)
    invoice_prefix: str | None = Field(default=None, max_length=20)
    invoice_postfix: str | None = Field(default=None, max_length=20)


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
