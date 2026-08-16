import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business
from app.security import decode_access_token
from app.token_revocation import is_token_revoked

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_business(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Business:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials"
    )
    try:
        payload = decode_access_token(token)
        business_id = uuid.UUID(payload["business_id"])
        jti = payload["jti"]
    except (JWTError, KeyError, ValueError):
        raise credentials_error

    # Signature and expiry alone aren't enough -- a token logged out via
    # POST /auth/logout is still cryptographically valid until it expires,
    # so it must also be checked against the revocation list.
    if is_token_revoked(jti):
        raise credentials_error

    business = db.get(Business, business_id)
    if business is None:
        raise credentials_error
    return business
