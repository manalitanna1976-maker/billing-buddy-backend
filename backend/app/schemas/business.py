import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants.indian_states import normalize_state
from app.validators import clean_optional_text, require_non_empty, validate_gstin

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

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else require_non_empty(v)

    @field_validator("address", "phone")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        return validate_gstin(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        v = clean_optional_text(v)
        if v is None:
            return None
        if "@" not in v or "." not in v.split("@")[-1] or " " in v:
            raise ValueError("invalid email address")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v: str | None) -> str | None:
        cleaned = clean_optional_text(v)
        if cleaned is None:
            return None
        return normalize_state(cleaned) or cleaned


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
