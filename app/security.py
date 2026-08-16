import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Fixed bcrypt hash with no matching plaintext -- used to burn a verify cycle
# for logins against an email that doesn't exist, so that response timing
# doesn't reveal whether the account exists (see verify_password_or_dummy).
_DUMMY_HASH = "$2b$12$Fy8qSly/8fgarQiJ9NFsMO1G14FYl0xUHOoDjZjz66nKGMVBdiLam"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def verify_password_or_dummy(password: str, hashed: str | None) -> bool:
    """Like verify_password, but always runs a bcrypt comparison even when
    `hashed` is None (no such user) -- verifying against `_DUMMY_HASH`
    instead of short-circuiting to False. Keeps "no such email" and "wrong
    password" responses the same shape in time, closing the user-enumeration
    timing side-channel on POST /auth/login."""
    return verify_password(password, hashed or _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID, business_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "business_id": str(business_id),
        "exp": expire,
        # Unique per token so a single one can be revoked on logout without
        # invalidating every other token issued to the same user (see
        # app/token_revocation.py).
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
