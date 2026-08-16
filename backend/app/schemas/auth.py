import re

from pydantic import AfterValidator, BaseModel, Field
from typing_extensions import Annotated

# Plain str + regex instead of pydantic's EmailStr: EmailStr (via
# email-validator) rejects reserved/special-use TLDs like `.test` by
# default with no way to opt out through pydantic's EmailStr config, and
# `.test` is the RFC 2606 reserved TLD this project's own test suite uses
# throughout. A simple format check is sufficient here — we are not
# verifying deliverability, only shape.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    if not _EMAIL_RE.match(value):
        raise ValueError("value is not a valid email address")
    return value


EmailStr = Annotated[str, AfterValidator(_validate_email)]


class SignupRequest(BaseModel):
    business_name: str
    email: EmailStr
    # The frontend enforces an 8-character minimum (AuthPage.tsx); enforce it
    # here too so the API can't be used directly (or by a future second
    # client) to create accounts with trivially weak passwords.
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
