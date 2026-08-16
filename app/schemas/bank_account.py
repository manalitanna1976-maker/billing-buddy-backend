import uuid

from pydantic import BaseModel, ConfigDict


class BankAccountCreate(BaseModel):
    bank_name: str
    account_no: str
    ifsc: str
    is_default: bool = False


class BankAccountUpdate(BaseModel):
    bank_name: str | None = None
    account_no: str | None = None
    ifsc: str | None = None
    is_default: bool | None = None


class BankAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bank_name: str
    account_no: str
    ifsc: str
    is_default: bool
