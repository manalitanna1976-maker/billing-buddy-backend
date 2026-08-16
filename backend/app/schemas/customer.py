import uuid

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    name: str
    address: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    gstin_pan: str | None = None
    place_of_supply: str | None = None
    reverse_charge: bool = False
    ship_to: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    gstin_pan: str | None = None
    place_of_supply: str | None = None
    reverse_charge: bool | None = None
    ship_to: str | None = None


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str | None
    contact_person: str | None
    phone: str | None
    gstin_pan: str | None
    place_of_supply: str | None
    reverse_charge: bool
    ship_to: str | None
