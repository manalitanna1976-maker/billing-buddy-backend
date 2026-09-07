import uuid

from pydantic import BaseModel, ConfigDict, field_validator

from app.constants.indian_states import normalize_state
from app.validators import (
    clean_optional_text,
    require_non_empty,
    validate_gstin,
    validate_pan,
)


class CustomerCreate(BaseModel):
    name: str
    address: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    gstin: str | None = None
    pan: str | None = None
    place_of_supply: str | None = None
    reverse_charge: bool = False
    ship_to: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return require_non_empty(v)

    @field_validator("address", "contact_person", "phone", "ship_to")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        return validate_gstin(v)

    @field_validator("pan")
    @classmethod
    def _pan(cls, v: str | None) -> str | None:
        return validate_pan(v)

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v: str | None) -> str | None:
        cleaned = clean_optional_text(v)
        if cleaned is None:
            return None
        # Accept anything, but canonicalise when we recognise it so GST
        # intra/inter-state detection is reliable.
        return normalize_state(cleaned) or cleaned


class CustomerUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    gstin: str | None = None
    pan: str | None = None
    place_of_supply: str | None = None
    reverse_charge: bool | None = None
    ship_to: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return None if v is None else require_non_empty(v)

    @field_validator("address", "contact_person", "phone", "ship_to")
    @classmethod
    def _optional_text(cls, v: str | None) -> str | None:
        return clean_optional_text(v)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        return validate_gstin(v)

    @field_validator("pan")
    @classmethod
    def _pan(cls, v: str | None) -> str | None:
        return validate_pan(v)

    @field_validator("place_of_supply")
    @classmethod
    def _pos(cls, v: str | None) -> str | None:
        cleaned = clean_optional_text(v)
        if cleaned is None:
            return None
        return normalize_state(cleaned) or cleaned


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None
    contact_person: str | None
    phone: str | None
    gstin: str | None
    pan: str | None
    place_of_supply: str | None
    reverse_charge: bool
    ship_to: str | None
