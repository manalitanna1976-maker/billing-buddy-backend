import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Business
from app.security import decode_access_token
from app.token_revocation import is_token_revoked

# auto_error=False: a request may authenticate via the httpOnly session cookie
# instead of the Authorization header, so a missing header is not itself an error.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

_settings = get_settings()


def _extract_token(request: Request, bearer: str | None) -> str | None:
    if bearer:
        return bearer
    return request.cookies.get(_settings.session_cookie_name)


def get_current_business(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Business:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials"
    )
    raw = _extract_token(request, token)
    if not raw:
        raise credentials_error
    try:
        payload = decode_access_token(raw)
        business_id = uuid.UUID(payload["business_id"])
        jti = payload["jti"]
    except (JWTError, KeyError, ValueError):
        raise credentials_error

    # Signature and expiry alone aren't enough -- a token logged out via
    # POST /auth/logout is still cryptographically valid until it expires,
    # so it must also be checked against the revocation list.
    if is_token_revoked(db, jti):
        raise credentials_error

    business = db.get(Business, business_id)
    if business is None:
        raise credentials_error
    return business
