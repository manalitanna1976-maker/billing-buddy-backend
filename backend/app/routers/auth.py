from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business, User
from app.rate_limit import is_login_rate_limited, record_failed_login, reset_failed_logins
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    business = Business(name=body.business_name)
    db.add(business)
    db.flush()

    user = User(business_id=business.id, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()

    token = create_access_token(user_id=user.id, business_id=business.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"

    # See app/rate_limit.py for the policy and rationale (per-email +
    # per-IP failed-attempt caps). Checked before touching the DB so a
    # locked-out caller can't be used to keep probing for account
    # existence via timing.
    if is_login_rate_limited(body.email, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again in a few minutes.",
        )

    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        record_failed_login(body.email, client_ip)
        raise unauthorized

    reset_failed_logins(body.email)
    token = create_access_token(user_id=user.id, business_id=user.business_id)
    return TokenResponse(access_token=token)
