from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import oauth2_scheme
from app.models import Business, User
from app.rate_limit import is_login_rate_limited, record_failed_login, reset_failed_logins
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse
from app.security import create_access_token, decode_access_token, hash_password, verify_password_or_dummy
from app.token_revocation import revoke_token

router = APIRouter(prefix="/auth", tags=["auth"])


already_registered = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise already_registered

    business = Business(name=body.business_name)
    db.add(business)
    db.flush()

    user = User(business_id=business.id, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # The pre-check above is TOCTOU: two concurrent signups for the same
        # email can both pass `existing is None` before either commits. The
        # DB's unique index on User.email (see app/models.py) is the real
        # guard -- catch its violation here and turn it into the same clean
        # 409 the pre-check gives, instead of an unhandled 500.
        db.rollback()
        raise already_registered

    token = create_access_token(user_id=user.id, business_id=business.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"

    # See app/rate_limit.py for the policy and rationale (per-email +
    # per-IP failed-attempt caps). Checked before touching the DB so a
    # locked-out caller can't be used to keep probing for account
    # existence via timing.
    if is_login_rate_limited(db, body.email, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again in a few minutes.",
        )

    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = db.query(User).filter(User.email == body.email).first()
    # Always run the bcrypt comparison, even when no user was found (against
    # a fixed dummy hash) -- otherwise a nonexistent email short-circuits
    # before hashing and returns measurably faster than a wrong password,
    # letting an attacker enumerate registered emails by response time.
    password_ok = verify_password_or_dummy(body.password, user.password_hash if user else None)
    if not user or not password_ok:
        record_failed_login(db, body.email, client_ip)
        raise unauthorized

    reset_failed_logins(db, body.email)
    token = create_access_token(user_id=user.id, business_id=user.business_id)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(token)
        jti = payload["jti"]
        exp = payload["exp"]
    except (JWTError, KeyError):
        # Already invalid, malformed, or expired -- nothing to revoke.
        # Logout is idempotent: either way, this token can't be used again.
        return
    revoke_token(db, jti, exp)
