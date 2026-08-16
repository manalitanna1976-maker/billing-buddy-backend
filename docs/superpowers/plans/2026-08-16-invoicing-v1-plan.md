# Billing Buddy CRM — Invoicing v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-tenant, India-GST-compliant sale invoice generator — signup/login, business profile (with logo/signature upload), customers, bank accounts, invoice CRUD with GST calc and auto-numbering, and a downloadable PDF matching the reference screenshot.

**Architecture:** FastAPI backend (Postgres via SQLAlchemy/Alembic, JWT auth, row-level tenant isolation via `business_id`) + React/Vite/TypeScript frontend (Tailwind, React Hook Form, TanStack Query). Server-side PDF rendering via Jinja2 + WeasyPrint.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Postgres, pydantic-settings, python-jose (JWT), passlib[bcrypt], WeasyPrint, pytest. React 18, Vite, TypeScript, Tailwind CSS, React Hook Form, TanStack Query, axios, zustand.

**Spec:** `docs/superpowers/specs/2026-08-16-invoicing-v1-design.md`

## Global Constraints

- Every tenant-owned table has a `business_id` column; every query that reads/writes tenant data MUST be scoped to the authenticated user's `business_id` — never trust a client-supplied business/tenant id.
- GST rate slabs: 0, 5, 12, 18, 28 (percent). Same state (`Business.state` == `Customer.place_of_supply`) → CGST+SGST (rate/2 each); different state → IGST (full rate).
- Money fields are `Decimal`, never `float`, on both the DB (`Numeric(12,2)`) and in Python calc code.
- Backend runs on `http://localhost:8000`, frontend dev server on `http://localhost:5173`, backend `CORS` allows the frontend origin.
- Uploaded files (logo, signature) live under `backend/uploads/{business_id}/` and are served at `/uploads/{business_id}/{filename}`.
- All IDs are UUIDs (Postgres `UUID` type, Python `uuid.uuid4()`).

---

## Task 1: Backend project scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/.env.example`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces: `app.config.Settings` (pydantic-settings, fields: `database_url: str`, `jwt_secret: str`, `jwt_algorithm: str = "HS256"`, `jwt_expire_minutes: int = 1440`, `upload_dir: str = "uploads"`, `cors_origins: list[str] = ["http://localhost:5173"]`), exposed as `get_settings()` (cached via `functools.lru_cache`).
- Produces: `app.main.app` — the FastAPI instance, with `/health` returning `{"status": "ok"}`.

- [ ] **Step 1: Set up the Python project**

```bash
mkdir -p backend/app backend/tests
cd backend
cat > pyproject.toml <<'EOF'
[project]
name = "billing-buddy-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "pydantic-settings>=2.5",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "python-multipart>=0.0.12",
    "weasyprint>=62",
    "jinja2>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "httpx>=0.27", "pytest-cov>=5.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
EOF
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 2: Write `.env.example`**

```
DATABASE_URL=postgresql+psycopg://billing:billing@localhost:5432/billing_buddy
JWT_SECRET=change-me-in-production
```

- [ ] **Step 3: Write `app/config.py`**

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    upload_dir: str = "uploads"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Write the failing test**

```python
# backend/tests/test_health.py
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 5: Write `tests/conftest.py`**

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://billing:billing@localhost:5432/billing_buddy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'` (or import error, since `app/main.py` doesn't exist yet).

- [ ] **Step 7: Write `app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Billing Buddy CRM API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml backend/.env.example backend/app backend/tests
git commit -m "feat(backend): scaffold FastAPI app with health check"
```

---

## Task 2: Database models and migration

**Files:**
- Create: `backend/app/db.py`
- Create: `backend/app/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_initial.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.get_settings` (Task 1)
- Produces: `app.db.Base` (SQLAlchemy declarative base), `app.db.engine`, `app.db.SessionLocal`, `app.db.get_db()` (FastAPI dependency yielding a `Session`)
- Produces: ORM classes in `app.models` — `Business`, `User`, `BankAccount`, `Customer`, `Invoice`, `InvoiceLineItem` — all with `id: UUID` primary key; `User`/`BankAccount`/`Customer`/`Invoice` FK to `Business.id` via an **indexed** `business_id` column (every tenant-scoped query filters on this — at high per-tenant row counts an unindexed FK is a full table scan). `Customer` and `Invoice` additionally carry a composite index — `(business_id, name)` and `(business_id, created_at)` respectively — matching the query patterns used by the list/search endpoints in Tasks 7 and 10.

- [ ] **Step 1: Write `app/db.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 2: Write `app/models.py`**

```python
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signature_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invoice_prefix: Mapped[str] = mapped_column(String(20), default="")
    invoice_postfix: Mapped[str] = mapped_column(String(20), default="")
    next_invoice_seq: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    bank_name: Mapped[str] = mapped_column(String(200))
    account_no: Mapped[str] = mapped_column(String(50))
    ifsc: Mapped[str] = mapped_column(String(11))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (Index("ix_customers_business_id_name", "business_id", "name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gstin_pan: Mapped[str | None] = mapped_column(String(15), nullable=True)
    place_of_supply: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reverse_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    ship_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_business_id_created_at", "business_id", "created_at"),
        Index("ux_invoices_business_id_invoice_no", "business_id", "invoice_no", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    invoice_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    invoice_no: Mapped[str] = mapped_column(String(50))
    invoice_date: Mapped[date] = mapped_column(Date)
    challan_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    challan_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    po_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    po_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lr_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    eway_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bank_accounts.id"), nullable=True
    )
    discount_type: Mapped[str] = mapped_column(String(3), default="Rs")  # "Rs" | "%"
    discount_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tcs: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    round_off: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    terms_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    taxable_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    payment_type: Mapped[str] = mapped_column(String(10), default="credit")
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | saved | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLineItem.sr_no"
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    sr_no: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(200))
    hsn_sac: Mapped[str | None] = mapped_column(String(10), nullable=True)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    uom: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")
```

- [ ] **Step 3: Initialize Alembic and write the initial migration**

```bash
cd backend
.venv/bin/alembic init alembic
```

Edit `backend/alembic/env.py` — replace the `target_metadata = None` line and add imports near the top:

```python
from app.config import get_settings
from app.db import Base
from app import models  # noqa: F401  (registers all model classes on Base.metadata)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

Generate the migration:

```bash
.venv/bin/alembic revision --autogenerate -m "initial schema"
```

- [ ] **Step 4: Write the failing test**

```python
# backend/tests/test_models.py
import uuid

from app.models import Business, User


def test_create_business_and_user(db_session):
    business = Business(name="Dattani Steel", state="Gujarat")
    db_session.add(business)
    db_session.flush()

    user = User(
        business_id=business.id,
        email="owner@dattanisteel.test",
        password_hash="hashed",
    )
    db_session.add(user)
    db_session.commit()

    assert isinstance(business.id, uuid.UUID)
    assert user.business_id == business.id
```

- [ ] **Step 5: Add a `db_session` fixture to `tests/conftest.py`**

```python
# append to backend/tests/conftest.py
from app.db import Base, engine, SessionLocal


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_models.py -v`
Expected: FAIL — connection error if `billing_buddy_test` DB doesn't exist yet. Create it: `createdb billing_buddy_test` (or via `psql -c "CREATE DATABASE billing_buddy_test"`), then rerun; expect FAIL with `NameError`/`ModuleNotFoundError` if `app/models.py` had a typo, otherwise this becomes a green run once models are correct — if it's green immediately, that's fine, the meaningful failure was covered by Step 4 not existing before Step 2.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/db.py backend/app/models.py backend/alembic.ini backend/alembic backend/tests
git commit -m "feat(backend): add SQLAlchemy models and initial migration"
```

---

## Task 3: Auth — signup, login, tenant dependency

**Files:**
- Create: `backend/app/security.py`
- Create: `backend/app/deps.py`
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `app.db.get_db` (Task 2), `app.models.Business`, `app.models.User` (Task 2)
- Produces: `app.security.hash_password(password: str) -> str`, `app.security.verify_password(password: str, hashed: str) -> bool`, `app.security.create_access_token(user_id: uuid.UUID, business_id: uuid.UUID) -> str`, `app.security.decode_access_token(token: str) -> dict` (raises `jose.JWTError` on invalid/expired)
- Produces: `app.deps.get_current_business(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> Business` — a FastAPI dependency every tenant-scoped router uses to resolve the caller's `Business` row from the JWT. Raises `HTTPException(401)` on invalid token or missing business.
- Produces: `POST /auth/signup` (body: `{business_name, email, password}` → `{access_token, token_type: "bearer"}`), `POST /auth/login` (body: `{email, password}` → same shape)

- [ ] **Step 1: Write `app/security.py`**

```python
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(user_id: uuid.UUID, business_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "business_id": str(business_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
```

- [ ] **Step 2: Write `app/schemas/auth.py`**

```python
from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    business_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
```

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/test_auth.py
def test_signup_then_login(client):
    signup_resp = client.post(
        "/auth/signup",
        json={
            "business_name": "Dattani Steel",
            "email": "owner@dattanisteel.test",
            "password": "correct horse battery staple",
        },
    )
    assert signup_resp.status_code == 201
    assert "access_token" in signup_resp.json()

    login_resp = client.post(
        "/auth/login",
        json={"email": "owner@dattanisteel.test", "password": "correct horse battery staple"},
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


def test_login_wrong_password_rejected(client):
    client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": "a@b.test", "password": "right-pass"},
    )
    resp = client.post("/auth/login", json={"email": "a@b.test", "password": "wrong-pass"})
    assert resp.status_code == 401


def test_signup_duplicate_email_rejected(client):
    payload = {"business_name": "Dattani Steel", "email": "dupe@b.test", "password": "pass1234"}
    first = client.post("/auth/signup", json=payload)
    assert first.status_code == 201
    second = client.post("/auth/signup", json=payload)
    assert second.status_code == 409
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_auth.py -v`
Expected: FAIL — `404 Not Found` (no `/auth/signup` route yet).

- [ ] **Step 5: Write `app/deps.py`**

```python
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business
from app.security import decode_access_token

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
    except (JWTError, KeyError, ValueError):
        raise credentials_error

    business = db.get(Business, business_id)
    if business is None:
        raise credentials_error
    return business
```

- [ ] **Step 6: Write `app/routers/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Business, User
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
def login(body: LoginRequest, db: Session = Depends(get_db)):
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise unauthorized

    token = create_access_token(user_id=user.id, business_id=user.business_id)
    return TokenResponse(access_token=token)
```

- [ ] **Step 7: Wire the router into `app/main.py`**

```python
# add near the top of backend/app/main.py
from app.routers import auth

# add after `app = FastAPI(...)` and the CORS middleware block
app.include_router(auth.router)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_auth.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/security.py backend/app/deps.py backend/app/schemas backend/app/routers/auth.py backend/app/main.py backend/tests/test_auth.py
git commit -m "feat(backend): add signup/login with JWT auth and tenant dependency"
```

---

## Task 4: Business profile API

**Files:**
- Create: `backend/app/schemas/business.py`
- Create: `backend/app/routers/business.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_business.py`

**Interfaces:**
- Consumes: `app.deps.get_current_business` (Task 3)
- Produces: `GET /business` → `BusinessRead`, `PUT /business` (body: `BusinessUpdate`) → `BusinessRead`
- Produces: `app.schemas.business.BusinessRead` fields: `id, name, gstin, address, state, phone, email, logo_url, signature_url, invoice_prefix, invoice_postfix`

- [ ] **Step 1: Write `app/schemas/business.py`**

```python
import uuid

from pydantic import BaseModel, ConfigDict


class BusinessUpdate(BaseModel):
    name: str | None = None
    gstin: str | None = None
    address: str | None = None
    state: str | None = None
    phone: str | None = None
    email: str | None = None
    invoice_prefix: str | None = None
    invoice_postfix: str | None = None


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
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_business.py
def _signup_and_headers(client, email="owner@biz.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_get_business_profile(client):
    headers = _signup_and_headers(client)
    resp = client.get("/business", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Dattani Steel"


def test_update_business_profile(client):
    headers = _signup_and_headers(client)
    resp = client.put(
        "/business",
        headers=headers,
        json={"gstin": "24AAAAA0000A1Z5", "state": "Gujarat"},
    )
    assert resp.status_code == 200
    assert resp.json()["gstin"] == "24AAAAA0000A1Z5"
    assert resp.json()["state"] == "Gujarat"


def test_business_requires_auth(client):
    resp = client.get("/business")
    assert resp.status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_business.py -v`
Expected: FAIL — `404 Not Found` (no `/business` route yet).

- [ ] **Step 4: Write `app/routers/business.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_business
from app.models import Business
from app.schemas.business import BusinessRead, BusinessUpdate

router = APIRouter(prefix="/business", tags=["business"])


@router.get("", response_model=BusinessRead)
def get_business(business: Business = Depends(get_current_business)):
    return business


@router.put("", response_model=BusinessRead)
def update_business(
    body: BusinessUpdate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(business, field, value)
    db.commit()
    db.refresh(business)
    return business
```

- [ ] **Step 5: Wire the router into `app/main.py`**

```python
# add alongside the auth import in backend/app/main.py
from app.routers import business

# add alongside app.include_router(auth.router)
app.include_router(business.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_business.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/business.py backend/app/routers/business.py backend/app/main.py backend/tests/test_business.py
git commit -m "feat(backend): add business profile get/update endpoints"
```

---

## Task 5: Logo and signature upload

**Files:**
- Create: `backend/app/storage.py`
- Modify: `backend/app/routers/business.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_uploads.py`

**Interfaces:**
- Consumes: `app.config.get_settings` (Task 1), `app.deps.get_current_business` (Task 3)
- Produces: `app.storage.save_upload(business_id: uuid.UUID, kind: str, filename: str, content: bytes) -> str` — validates both the file extension *and* the content's magic bytes (rejects a relabeled non-image even if the extension looks legitimate), writes to `uploads/{business_id}/{kind}{ext}`, returns the URL path `/uploads/{business_id}/{kind}{ext}` to store on the model. Raises `ValueError` on either check failing.
- Produces: `POST /business/logo` (multipart `file`) → `BusinessRead`, `POST /business/signature` (multipart `file`) → `BusinessRead`

- [ ] **Step 1: Write `app/storage.py`**

```python
import uuid
from pathlib import Path

from app.config import get_settings

settings = get_settings()
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Magic-byte signatures — the extension alone doesn't prove the content is
# actually an image; a relabeled arbitrary file would otherwise be accepted
# and served back to browsers from /uploads/...
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


def _looks_like_image(ext: str, content: bytes) -> bool:
    if ext == ".png":
        return content.startswith(_PNG_SIGNATURE)
    if ext in (".jpg", ".jpeg"):
        return content.startswith(_JPEG_SIGNATURE)
    return False


def save_upload(business_id: uuid.UUID, kind: str, filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")
    if not _looks_like_image(ext, content):
        raise ValueError("File content does not match a supported image format")

    business_dir = Path(settings.upload_dir) / str(business_id)
    business_dir.mkdir(parents=True, exist_ok=True)

    dest = business_dir / f"{kind}{ext}"
    dest.write_bytes(content)

    return f"/uploads/{business_id}/{kind}{ext}"
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_uploads.py
import io


def _signup_and_headers(client, email="owner@upload.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # minimal valid PNG signature + padding


def test_upload_logo(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    headers = _signup_and_headers(client)

    file_bytes = io.BytesIO(PNG_MAGIC_BYTES)
    resp = client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("logo.png", file_bytes, "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["logo_url"].endswith("/logo.png")


def test_upload_rejects_bad_extension(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    headers = _signup_and_headers(client)

    file_bytes = io.BytesIO(PNG_MAGIC_BYTES)
    resp = client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("virus.exe", file_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_upload_rejects_content_not_matching_extension(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    headers = _signup_and_headers(client)

    file_bytes = io.BytesIO(b"this is not an image, just relabeled as one")
    resp = client.post(
        "/business/logo",
        headers=headers,
        files={"file": ("logo.png", file_bytes, "image/png")},
    )
    assert resp.status_code == 422
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_uploads.py -v`
Expected: FAIL — `404 Not Found` (no `/business/logo` route yet).

- [ ] **Step 4: Add upload endpoints to `app/routers/business.py`**

```python
# add to backend/app/routers/business.py
from fastapi import File, HTTPException, UploadFile

from app.storage import save_upload


@router.post("/logo", response_model=BusinessRead)
async def upload_logo(
    file: UploadFile = File(...),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        url = save_upload(business.id, "logo", file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    business.logo_url = url
    db.commit()
    db.refresh(business)
    return business


@router.post("/signature", response_model=BusinessRead)
async def upload_signature(
    file: UploadFile = File(...),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    content = await file.read()
    try:
        url = save_upload(business.id, "signature", file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    business.signature_url = url
    db.commit()
    db.refresh(business)
    return business
```

- [ ] **Step 5: Serve uploaded files as static assets in `app/main.py`**

```python
# add near the top of backend/app/main.py
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app.config import get_settings

# add after app.include_router(business.router)
Path(get_settings().upload_dir).mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=get_settings().upload_dir), name="uploads")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_uploads.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage.py backend/app/routers/business.py backend/app/main.py backend/tests/test_uploads.py
git commit -m "feat(backend): add logo/signature upload endpoints and static file serving"
```

---

## Task 6: Bank accounts CRUD

**Files:**
- Create: `backend/app/schemas/bank_account.py`
- Create: `backend/app/routers/bank_accounts.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_bank_accounts.py`

**Interfaces:**
- Consumes: `app.deps.get_current_business` (Task 3)
- Produces: `GET /bank-accounts` → `list[BankAccountRead]`, `POST /bank-accounts` (body: `BankAccountCreate`) → `BankAccountRead` (201), `PUT /bank-accounts/{id}` → `BankAccountRead`, `DELETE /bank-accounts/{id}` → 204. All scoped to `business.id`; a request for an id belonging to another business returns 404.

- [ ] **Step 1: Write `app/schemas/bank_account.py`**

```python
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
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_bank_accounts.py
def _headers(client, email="owner@bank.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_list_update_delete_bank_account(client):
    headers = _headers(client)

    create_resp = client.post(
        "/bank-accounts",
        headers=headers,
        json={"bank_name": "HDFC Bank", "account_no": "1234567890", "ifsc": "HDFC0000123"},
    )
    assert create_resp.status_code == 201
    account_id = create_resp.json()["id"]

    list_resp = client.get("/bank-accounts", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    update_resp = client.put(
        f"/bank-accounts/{account_id}", headers=headers, json={"is_default": True}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["is_default"] is True

    delete_resp = client.delete(f"/bank-accounts/{account_id}", headers=headers)
    assert delete_resp.status_code == 204
    assert client.get("/bank-accounts", headers=headers).json() == []


def test_bank_account_isolated_per_tenant(client):
    headers_a = _headers(client, "a@bank.test")
    headers_b = _headers(client, "b@bank.test")

    create_resp = client.post(
        "/bank-accounts",
        headers=headers_a,
        json={"bank_name": "HDFC Bank", "account_no": "111", "ifsc": "HDFC0000111"},
    )
    account_id = create_resp.json()["id"]

    resp = client.put(f"/bank-accounts/{account_id}", headers=headers_b, json={"is_default": True})
    assert resp.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_bank_accounts.py -v`
Expected: FAIL — `404 Not Found` on `POST /bank-accounts` (route doesn't exist yet — distinguish from the intentional 404 assertion in `test_bank_account_isolated_per_tenant` by checking the first test fails at creation).

- [ ] **Step 4: Write `app/routers/bank_accounts.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_business
from app.models import BankAccount, Business
from app.schemas.bank_account import BankAccountCreate, BankAccountRead, BankAccountUpdate

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


def _get_owned_or_404(db: Session, business: Business, account_id: uuid.UUID) -> BankAccount:
    account = db.get(BankAccount, account_id)
    if account is None or account.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found")
    return account


@router.get("", response_model=list[BankAccountRead])
def list_bank_accounts(
    business: Business = Depends(get_current_business), db: Session = Depends(get_db)
):
    return db.query(BankAccount).filter(BankAccount.business_id == business.id).all()


@router.post("", response_model=BankAccountRead, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    body: BankAccountCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    account = BankAccount(business_id=business.id, **body.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.put("/{account_id}", response_model=BankAccountRead)
def update_bank_account(
    account_id: uuid.UUID,
    body: BankAccountUpdate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    account = _get_owned_or_404(db, business, account_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    account_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    account = _get_owned_or_404(db, business, account_id)
    db.delete(account)
    db.commit()
```

- [ ] **Step 5: Wire the router into `app/main.py`**

```python
# add alongside the other router imports in backend/app/main.py
from app.routers import bank_accounts

# add alongside the other app.include_router(...) calls
app.include_router(bank_accounts.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_bank_accounts.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/bank_account.py backend/app/routers/bank_accounts.py backend/app/main.py backend/tests/test_bank_accounts.py
git commit -m "feat(backend): add bank accounts CRUD with tenant isolation"
```

---

## Task 7: Customers CRUD (lightweight, autocomplete)

**Files:**
- Create: `backend/app/schemas/customer.py`
- Create: `backend/app/routers/customers.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_customers.py`

**Interfaces:**
- Consumes: `app.deps.get_current_business` (Task 3)
- Produces: `GET /customers?q=<search>&limit=<n>&offset=<n>` → `list[CustomerRead]` (case-insensitive substring match on `name`, ordered by `name`; `q` optional — omitted means "all"; `limit` default 50, max 200; `offset` default 0 — required at scale since a tenant can accumulate far more customers than a single response should carry), `POST /customers` → `CustomerRead` (201), `GET /customers/{id}` → `CustomerRead`, `PUT /customers/{id}` → `CustomerRead`. All scoped to `business.id`.

- [ ] **Step 1: Write `app/schemas/customer.py`**

```python
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
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_customers.py
def _headers(client, email="owner@cust.test"):
    resp = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_and_search_customers(client):
    headers = _headers(client)

    client.post(
        "/customers",
        headers=headers,
        json={"name": "Acme Traders", "place_of_supply": "Maharashtra"},
    )
    client.post(
        "/customers", headers=headers, json={"name": "Beta Corp", "place_of_supply": "Gujarat"}
    )

    resp = client.get("/customers", headers=headers, params={"q": "acme"})
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["Acme Traders"]


def test_update_customer(client):
    headers = _headers(client)
    create_resp = client.post("/customers", headers=headers, json={"name": "Acme Traders"})
    customer_id = create_resp.json()["id"]

    update_resp = client.put(
        f"/customers/{customer_id}", headers=headers, json={"gstin_pan": "27AAAAA0000A1Z5"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["gstin_pan"] == "27AAAAA0000A1Z5"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_customers.py -v`
Expected: FAIL — `404 Not Found` (no `/customers` route yet).

- [ ] **Step 4: Write `app/routers/customers.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Customer
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


def _get_owned_or_404(db: Session, business: Business, customer_id: uuid.UUID) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("", response_model=list[CustomerRead])
def list_customers(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    query = db.query(Customer).filter(Customer.business_id == business.id)
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%"))
    return query.order_by(Customer.name).offset(offset).limit(limit).all()


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CustomerCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    customer = Customer(business_id=business.id, **body.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, business, customer_id)


@router.put("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    customer = _get_owned_or_404(db, business, customer_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer
```

- [ ] **Step 5: Wire the router into `app/main.py`**

```python
# add alongside the other router imports in backend/app/main.py
from app.routers import customers

# add alongside the other app.include_router(...) calls
app.include_router(customers.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_customers.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/customer.py backend/app/routers/customers.py backend/app/main.py backend/tests/test_customers.py
git commit -m "feat(backend): add customers CRUD with name search"
```

---

## Task 8: GST calculation service (pure logic)

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/gst.py`
- Create: `backend/app/services/num2words_inr.py`
- Test: `backend/tests/services/test_gst.py`
- Test: `backend/tests/services/test_num2words_inr.py`

**Interfaces:**
- Produces: `app.services.gst.LineItemInput` (dataclass: `qty: Decimal, price: Decimal, discount: Decimal, gst_rate: Decimal`)
- Produces: `app.services.gst.line_taxable_value(item: LineItemInput) -> Decimal` — `(qty * price) - discount`
- Produces: `app.services.gst.split_gst(taxable: Decimal, gst_rate: Decimal, same_state: bool) -> dict` — `{"cgst": Decimal, "sgst": Decimal, "igst": Decimal}`, exactly two of the three are zero
- Produces: `app.services.gst.InvoiceTotals` (dataclass: `taxable_total, cgst_total, sgst_total, igst_total, tax_total, discount_amount, tcs_amount, round_off_amount, grand_total: Decimal`; `amount_in_words: str`)
- Produces: `app.services.gst.compute_invoice_totals(items: list[LineItemInput], same_state: bool, discount_type: str, discount_value: Decimal, tcs: Decimal, round_off: bool) -> InvoiceTotals`
- Produces: `app.services.num2words_inr.amount_in_words(amount: Decimal) -> str` — e.g. `Decimal("1234.50")` → `"One Thousand Two Hundred Thirty Four Rupees And Fifty Paise Only"`; `Decimal("0")` → `"Zero Rupees Only"`

- [ ] **Step 1: Write the failing tests for `num2words_inr` (simpler, build this first)**

```bash
mkdir -p backend/tests/services
touch backend/tests/services/__init__.py
```

```python
# backend/tests/services/test_num2words_inr.py
from decimal import Decimal

from app.services.num2words_inr import amount_in_words


def test_zero():
    assert amount_in_words(Decimal("0")) == "Zero Rupees Only"


def test_whole_rupees():
    assert amount_in_words(Decimal("100")) == "One Hundred Rupees Only"


def test_rupees_and_paise():
    assert amount_in_words(Decimal("1234.50")) == (
        "One Thousand Two Hundred Thirty Four Rupees And Fifty Paise Only"
    )


def test_lakhs():
    assert amount_in_words(Decimal("150000")) == "One Lakh Fifty Thousand Rupees Only"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/services/test_num2words_inr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.num2words_inr'`

- [ ] **Step 3: Write `app/services/num2words_inr.py`**

```python
from decimal import Decimal

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
]


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return f"{_TENS[tens]} {_ONES[ones]}".strip()


def _three_digits(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digits(rest))
    return " ".join(parts)


def _int_to_words(n: int) -> str:
    if n == 0:
        return ""
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    hundred = n

    parts = []
    if crore:
        parts.append(f"{_int_to_words(crore)} Crore")
    if lakh:
        parts.append(f"{_two_digits(lakh) if lakh < 100 else _three_digits(lakh)} Lakh")
    if thousand:
        parts.append(f"{_two_digits(thousand) if thousand < 100 else _three_digits(thousand)} Thousand")
    if hundred:
        parts.append(_three_digits(hundred))
    return " ".join(p for p in parts if p)


def amount_in_words(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    if rupees == 0 and paise == 0:
        return "Zero Rupees Only"

    words = f"{_int_to_words(rupees)} Rupees".strip() if rupees else ""
    if paise:
        paise_words = f"And {_two_digits(paise)} Paise"
        words = f"{words} {paise_words}".strip() if words else f"{paise_words.removeprefix('And ')}"
    return f"{words} Only".strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/services/test_num2words_inr.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for `gst`**

```python
# backend/tests/services/test_gst.py
from decimal import Decimal

from app.services.gst import LineItemInput, compute_invoice_totals, line_taxable_value, split_gst


def test_line_taxable_value():
    item = LineItemInput(qty=Decimal("10"), price=Decimal("100"), discount=Decimal("50"), gst_rate=Decimal("18"))
    assert line_taxable_value(item) == Decimal("950")


def test_split_gst_same_state_splits_cgst_sgst():
    result = split_gst(Decimal("1000"), Decimal("18"), same_state=True)
    assert result == {"cgst": Decimal("90.00"), "sgst": Decimal("90.00"), "igst": Decimal("0.00")}


def test_split_gst_different_state_uses_igst():
    result = split_gst(Decimal("1000"), Decimal("18"), same_state=False)
    assert result == {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("180.00")}


def test_compute_invoice_totals_single_item_same_state():
    items = [LineItemInput(qty=Decimal("2"), price=Decimal("500"), discount=Decimal("0"), gst_rate=Decimal("18"))]
    totals = compute_invoice_totals(
        items, same_state=True, discount_type="Rs", discount_value=Decimal("0"),
        tcs=Decimal("0"), round_off=False,
    )
    assert totals.taxable_total == Decimal("1000.00")
    assert totals.cgst_total == Decimal("90.00")
    assert totals.sgst_total == Decimal("90.00")
    assert totals.igst_total == Decimal("0.00")
    assert totals.tax_total == Decimal("180.00")
    assert totals.grand_total == Decimal("1180.00")
    assert totals.amount_in_words.startswith("One Thousand One Hundred Eighty Rupees")


def test_compute_invoice_totals_applies_percent_discount_and_round_off():
    items = [LineItemInput(qty=Decimal("1"), price=Decimal("999"), discount=Decimal("0"), gst_rate=Decimal("0"))]
    totals = compute_invoice_totals(
        items, same_state=True, discount_type="%", discount_value=Decimal("10"),
        tcs=Decimal("0"), round_off=True,
    )
    # 999 - 10% = 899.10 taxable, no tax, round-off to nearest rupee -> 899
    assert totals.discount_amount == Decimal("99.90")
    assert totals.grand_total == Decimal("899.00")
    assert totals.round_off_amount == Decimal("-0.10")
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/services/test_gst.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.gst'`

- [ ] **Step 7: Write `app/services/gst.py`**

```python
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.services.num2words_inr import amount_in_words as _amount_in_words

TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class LineItemInput:
    qty: Decimal
    price: Decimal
    discount: Decimal
    gst_rate: Decimal


@dataclass
class InvoiceTotals:
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    tax_total: Decimal
    discount_amount: Decimal
    tcs_amount: Decimal
    round_off_amount: Decimal
    grand_total: Decimal
    amount_in_words: str


def line_taxable_value(item: LineItemInput) -> Decimal:
    return _q(item.qty * item.price - item.discount)


def split_gst(taxable: Decimal, gst_rate: Decimal, same_state: bool) -> dict:
    tax = _q(taxable * gst_rate / Decimal("100"))
    if same_state:
        half = _q(tax / 2)
        return {"cgst": half, "sgst": tax - half, "igst": Decimal("0.00")}
    return {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": tax}


def compute_invoice_totals(
    items: list[LineItemInput],
    same_state: bool,
    discount_type: str,
    discount_value: Decimal,
    tcs: Decimal,
    round_off: bool,
) -> InvoiceTotals:
    line_taxables = [line_taxable_value(item) for item in items]
    subtotal = _q(sum(line_taxables, Decimal("0")))

    if discount_type == "%":
        discount_amount = _q(subtotal * discount_value / Decimal("100"))
    else:
        discount_amount = _q(discount_value)

    taxable_total = _q(subtotal - discount_amount)

    # Tax computed per line on its pre-discount taxable value (matches the
    # reference form: discount is a header-level adjustment, not per-line).
    cgst_total = sgst_total = igst_total = Decimal("0.00")
    for item, line_taxable in zip(items, line_taxables):
        split = split_gst(line_taxable, item.gst_rate, same_state)
        cgst_total += split["cgst"]
        sgst_total += split["sgst"]
        igst_total += split["igst"]

    tax_total = _q(cgst_total + sgst_total + igst_total)
    tcs_amount = _q(tcs)

    pre_round_total = _q(taxable_total + tax_total + tcs_amount)

    if round_off:
        grand_total = pre_round_total.to_integral_value(rounding=ROUND_HALF_UP)
        round_off_amount = _q(grand_total - pre_round_total)
    else:
        grand_total = pre_round_total
        round_off_amount = Decimal("0.00")

    return InvoiceTotals(
        taxable_total=taxable_total,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        tax_total=tax_total,
        discount_amount=discount_amount,
        tcs_amount=tcs_amount,
        round_off_amount=round_off_amount,
        grand_total=_q(grand_total),
        amount_in_words=_amount_in_words(_q(grand_total)),
    )
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/services/test_gst.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services backend/tests/services
git commit -m "feat(backend): add GST calculation and INR amount-in-words services"
```

---

## Task 9: Invoice numbering service

**Files:**
- Create: `backend/app/services/numbering.py`
- Test: `backend/tests/services/test_numbering.py`

**Interfaces:**
- Consumes: `app.models.Business` (Task 2)
- Produces: `app.services.numbering.next_invoice_number(db: Session, business: Business) -> str` — locks the business row (`SELECT ... FOR UPDATE`), returns `f"{business.invoice_prefix}{business.next_invoice_seq}{business.invoice_postfix}"`, increments and persists `business.next_invoice_seq` on the same transaction. Caller is responsible for `db.commit()`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_numbering.py
from app.models import Business
from app.services.numbering import next_invoice_number


def test_next_invoice_number_increments_sequence(db_session):
    business = Business(name="Dattani Steel", invoice_prefix="INV-", invoice_postfix="", next_invoice_seq=89)
    db_session.add(business)
    db_session.commit()

    first = next_invoice_number(db_session, business)
    db_session.commit()
    second = next_invoice_number(db_session, business)
    db_session.commit()

    assert first == "INV-89"
    assert second == "INV-90"


def test_next_invoice_number_applies_postfix(db_session):
    business = Business(name="Dattani Steel", invoice_prefix="", invoice_postfix="/26-27", next_invoice_seq=1)
    db_session.add(business)
    db_session.commit()

    assert next_invoice_number(db_session, business) == "1/26-27"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/services/test_numbering.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.numbering'`

- [ ] **Step 3: Write `app/services/numbering.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business


def next_invoice_number(db: Session, business: Business) -> str:
    locked = db.execute(
        select(Business).where(Business.id == business.id).with_for_update()
    ).scalar_one()

    seq = locked.next_invoice_seq
    number = f"{locked.invoice_prefix}{seq}{locked.invoice_postfix}"

    locked.next_invoice_seq = seq + 1
    business.next_invoice_seq = seq + 1

    return number
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/services/test_numbering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/numbering.py backend/tests/services/test_numbering.py
git commit -m "feat(backend): add invoice auto-numbering service"
```

---

## Task 10: Invoice CRUD API (GST calc + numbering integration)

**Files:**
- Create: `backend/app/schemas/invoice.py`
- Create: `backend/app/routers/invoices.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_invoices.py`

**Interfaces:**
- Consumes: `app.deps.get_current_business` (Task 3), `app.services.gst.{LineItemInput, compute_invoice_totals}` (Task 8), `app.services.numbering.next_invoice_number` (Task 9), `app.models.{Invoice, InvoiceLineItem, Customer}` (Task 2)
- Produces: `POST /invoices` (body: `InvoiceCreate`) → `InvoiceRead` (201) — computes `same_state` from `business.state == customer.place_of_supply`, calls `compute_invoice_totals`, persists `Invoice` + `InvoiceLineItem` rows with computed totals, assigns `invoice_no` via `next_invoice_number`
- Produces: `GET /invoices?limit=<n>&offset=<n>` → `list[InvoiceListItem]` (id, invoice_no, invoice_date, customer name, grand_total, status; ordered newest-first; `limit` default 50, max 200; `offset` default 0 — required at scale, a single tenant can accumulate up to and beyond 1M invoices and the list endpoint must never attempt to load them all into one response), `GET /invoices/{id}` → `InvoiceRead` (full detail incl. line items and totals), `PUT /invoices/{id}` → `InvoiceRead` (recomputes totals the same way), `DELETE /invoices/{id}` → `InvoiceRead` (200) — **soft delete**: sets `status = "cancelled"`, row and `invoice_no` are retained. GST invoice numbers are sequential and legally significant; a hard delete would leave a silent, unexplained gap in the sequence with no record the invoice ever existed. `(business_id, invoice_no)` also carries a unique constraint (Task 2) so the numbering service can never silently double-assign a number.

- [ ] **Step 1: Write `app/schemas/invoice.py`**

```python
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InvoiceLineItemInput(BaseModel):
    product_name: str
    hsn_sac: str | None = None
    qty: Decimal
    uom: str | None = None
    price: Decimal
    discount: Decimal = Decimal("0")
    gst_rate: Decimal = Decimal("0")


class InvoiceLineItemRead(InvoiceLineItemInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sr_no: int
    line_total: Decimal


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_type: str | None = None
    invoice_date: date
    challan_no: str | None = None
    challan_date: date | None = None
    po_no: str | None = None
    po_date: date | None = None
    lr_no: str | None = None
    eway_no: str | None = None
    delivery_mode: str | None = None
    due_date: date | None = None
    bank_account_id: uuid.UUID | None = None
    discount_type: str = "Rs"
    discount_value: Decimal = Decimal("0")
    tcs: Decimal = Decimal("0")
    round_off: bool = True
    terms_title: str | None = None
    terms_detail: str | None = None
    notes: str | None = None
    remarks: str | None = None
    payment_type: str = "credit"
    line_items: list[InvoiceLineItemInput]


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    invoice_type: str | None
    invoice_date: date
    customer_id: uuid.UUID
    challan_no: str | None
    challan_date: date | None
    po_no: str | None
    po_date: date | None
    lr_no: str | None
    eway_no: str | None
    delivery_mode: str | None
    due_date: date | None
    bank_account_id: uuid.UUID | None
    discount_type: str
    discount_value: Decimal
    tcs: Decimal
    round_off: bool
    terms_title: str | None
    terms_detail: str | None
    notes: str | None
    remarks: str | None
    taxable_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    payment_type: str
    status: str
    line_items: list[InvoiceLineItemRead]


class InvoiceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_no: str
    invoice_date: date
    grand_total: Decimal
    status: str
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_invoices.py
from decimal import Decimal


def _setup(client, email="owner@inv.test"):
    signup = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    client.put("/business", headers=headers, json={"state": "Gujarat"})

    customer = client.post(
        "/customers", headers=headers, json={"name": "Acme Traders", "place_of_supply": "Gujarat"}
    )
    return headers, customer.json()["id"]


def test_create_invoice_computes_totals_and_number(client):
    headers, customer_id = _setup(client)

    resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [
                {"product_name": "Steel Rod", "qty": "2", "price": "500", "gst_rate": "18"}
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["invoice_no"] == "1"
    # Pydantic v2 serializes Decimal to a JSON number, not a fixed-format
    # string — compare by value via Decimal, not raw string equality.
    assert Decimal(str(body["taxable_total"])) == Decimal("1000.00")
    assert Decimal(str(body["tax_total"])) == Decimal("180.00")
    assert Decimal(str(body["grand_total"])) == Decimal("1180.00")
    assert len(body["line_items"]) == 1

    second = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Bolt", "qty": "1", "price": "10", "gst_rate": "0"}],
        },
    )
    assert second.json()["invoice_no"] == "2"


def test_list_and_get_invoice(client):
    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice_id = create_resp.json()["id"]

    list_resp = client.get("/invoices", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    get_resp = client.get(f"/invoices/{invoice_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == invoice_id


def test_invoice_cross_tenant_404(client):
    headers_a, customer_id_a = _setup(client, "a@inv.test")
    headers_b, _ = _setup(client, "b@inv.test")

    create_resp = client.post(
        "/invoices",
        headers=headers_a,
        json={
            "customer_id": customer_id_a,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice_id = create_resp.json()["id"]

    resp = client.get(f"/invoices/{invoice_id}", headers=headers_b)
    assert resp.status_code == 404


def test_delete_invoice_is_a_soft_cancel(client):
    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    invoice_id = create_resp.json()["id"]
    invoice_no = create_resp.json()["invoice_no"]

    delete_resp = client.delete(f"/invoices/{invoice_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "cancelled"

    # row and invoice_no are retained, not removed — GST numbers must not
    # silently disappear
    get_resp = client.get(f"/invoices/{invoice_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "cancelled"
    assert get_resp.json()["invoice_no"] == invoice_no


def test_duplicate_invoice_no_rejected_by_unique_constraint(client, db_session):
    # Attempt to insert a second row with the same (business_id, invoice_no)
    # directly at the DB layer — this is what the unique index must block,
    # independent of whatever the numbering service does.
    import uuid as uuid_module
    from datetime import date

    from sqlalchemy.exc import IntegrityError

    from app.models import Invoice

    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "1", "price": "100", "gst_rate": "0"}],
        },
    )
    original = db_session.query(Invoice).filter(Invoice.invoice_no == create_resp.json()["invoice_no"]).one()

    duplicate = Invoice(
        business_id=original.business_id,
        customer_id=uuid_module.UUID(customer_id),
        invoice_no=original.invoice_no,
        invoice_date=date(2026, 8, 16),
    )
    db_session.add(duplicate)

    try:
        db_session.commit()
        assert False, "expected IntegrityError from unique (business_id, invoice_no) index"
    except IntegrityError:
        db_session.rollback()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_invoices.py -v`
Expected: FAIL — `404 Not Found` (no `/invoices` route yet).

- [ ] **Step 4: Write `app/routers/invoices.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Customer, Invoice, InvoiceLineItem
from app.schemas.invoice import InvoiceCreate, InvoiceListItem, InvoiceRead
from app.services.gst import LineItemInput, compute_invoice_totals
from app.services.numbering import next_invoice_number

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _get_owned_or_404(db: Session, business: Business, invoice_id: uuid.UUID) -> Invoice:
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.line_items))
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if invoice is None or invoice.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


def _apply_totals_and_items(invoice: Invoice, body: InvoiceCreate, business: Business, customer: Customer):
    same_state = bool(business.state) and business.state == customer.place_of_supply
    calc_items = [
        LineItemInput(qty=li.qty, price=li.price, discount=li.discount, gst_rate=li.gst_rate)
        for li in body.line_items
    ]
    totals = compute_invoice_totals(
        calc_items,
        same_state=same_state,
        discount_type=body.discount_type,
        discount_value=body.discount_value,
        tcs=body.tcs,
        round_off=body.round_off,
    )

    invoice.line_items.clear()
    for sr_no, (li, calc_item) in enumerate(zip(body.line_items, calc_items), start=1):
        from app.services.gst import line_taxable_value

        invoice.line_items.append(
            InvoiceLineItem(
                sr_no=sr_no,
                product_name=li.product_name,
                hsn_sac=li.hsn_sac,
                qty=li.qty,
                uom=li.uom,
                price=li.price,
                discount=li.discount,
                gst_rate=li.gst_rate,
                line_total=line_taxable_value(calc_item),
            )
        )

    invoice.taxable_total = totals.taxable_total
    invoice.tax_total = totals.tax_total
    invoice.grand_total = totals.grand_total


@router.get("", response_model=list[InvoiceListItem])
def list_invoices(
    limit: int = 50,
    offset: int = 0,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    return (
        db.query(Invoice)
        .filter(Invoice.business_id == business.id)
        .order_by(Invoice.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    invoice = Invoice(
        business_id=business.id,
        customer_id=body.customer_id,
        invoice_no=next_invoice_number(db, business),
        **body.model_dump(exclude={"customer_id", "line_items"}),
    )
    _apply_totals_and_items(invoice, body, business, customer)

    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, business, invoice_id)


@router.put("/{invoice_id}", response_model=InvoiceRead)
def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    invoice = _get_owned_or_404(db, business, invoice_id)
    customer = db.get(Customer, body.customer_id)
    if customer is None or customer.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    for field, value in body.model_dump(exclude={"customer_id", "line_items"}).items():
        setattr(invoice, field, value)
    invoice.customer_id = body.customer_id
    _apply_totals_and_items(invoice, body, business, customer)

    db.commit()
    db.refresh(invoice)
    return invoice


@router.delete("/{invoice_id}", response_model=InvoiceRead)
def cancel_invoice(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    # Soft delete only: GST invoice numbers are sequential and legally
    # significant, so a hard delete would leave an unexplained gap with no
    # record the invoice ever existed. Cancelling preserves the row and its
    # invoice_no while marking it void.
    invoice = _get_owned_or_404(db, business, invoice_id)
    invoice.status = "cancelled"
    db.commit()
    db.refresh(invoice)
    return invoice
```

- [ ] **Step 5: Wire the router into `app/main.py`**

```python
# add alongside the other router imports in backend/app/main.py
from app.routers import invoices

# add alongside the other app.include_router(...) calls
app.include_router(invoices.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_invoices.py -v`
Expected: PASS

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/invoice.py backend/app/routers/invoices.py backend/app/main.py backend/tests/test_invoices.py
git commit -m "feat(backend): add invoice CRUD with GST totals and auto-numbering"
```

---

## Task 11: PDF generation and download

**Files:**
- Create: `backend/app/templates/invoice.html`
- Create: `backend/app/services/pdf.py`
- Modify: `backend/app/routers/invoices.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_invoice_pdf.py`

**Interfaces:**
- Consumes: `app.models.Invoice` (with `line_items`, `customer`, `business` reachable via relationship — add `customer` and `business` relationships to `Invoice` in this task), `app.services.num2words_inr.amount_in_words` (Task 8)
- Produces: `app.services.pdf.render_invoice_pdf(invoice: Invoice) -> bytes`
- Produces: `GET /invoices/{id}/pdf` → `Response` with `media_type="application/pdf"` and header `Content-Disposition: attachment; filename="{invoice_no}.pdf"`

- [ ] **Step 1: Add `customer` and `business` relationships to `Invoice` in `app/models.py`**

```python
# in the Invoice class in backend/app/models.py, alongside the existing
# `line_items` relationship, add:
    customer: Mapped["Customer"] = relationship()
    business: Mapped["Business"] = relationship()
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_invoice_pdf.py
def _setup(client, email="owner@pdf.test"):
    signup = client.post(
        "/auth/signup",
        json={"business_name": "Dattani Steel", "email": email, "password": "pass1234"},
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}
    client.put("/business", headers=headers, json={"state": "Gujarat"})

    customer = client.post(
        "/customers", headers=headers, json={"name": "Acme Traders", "place_of_supply": "Gujarat"}
    )
    return headers, customer.json()["id"]


def test_download_invoice_pdf(client):
    headers, customer_id = _setup(client)
    create_resp = client.post(
        "/invoices",
        headers=headers,
        json={
            "customer_id": customer_id,
            "invoice_date": "2026-08-16",
            "line_items": [{"product_name": "Steel Rod", "qty": "2", "price": "500", "gst_rate": "18"}],
        },
    )
    invoice_id = create_resp.json()["id"]
    invoice_no = create_resp.json()["invoice_no"]

    resp = client.get(f"/invoices/{invoice_id}/pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert f'filename="{invoice_no}.pdf"' in resp.headers["content-disposition"]
    assert resp.content[:4] == b"%PDF"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_invoice_pdf.py -v`
Expected: FAIL — `404 Not Found` (no `/invoices/{id}/pdf` route yet).

- [ ] **Step 4: Write the placeholder template `app/templates/invoice.html`**

This is the initial layout matching the reference screenshot's structure (customer info, invoice detail, line items table, totals). It will be swapped for the user-supplied template later without touching `app/services/pdf.py`.

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body { font-family: sans-serif; font-size: 11px; color: #1a1a1a; }
  h1 { font-size: 16px; margin-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; }
  .totals { margin-top: 12px; width: 40%; margin-left: auto; }
  .totals td { border: none; padding: 2px 6px; }
  .grand-total { font-weight: bold; background: #fef9c3; }
  .header-row { display: flex; justify-content: space-between; }
  .logo { max-height: 60px; }
  .signature { max-height: 50px; margin-top: 20px; }
</style>
</head>
<body>
  <div class="header-row">
    <div>
      {% if business.logo_url %}<img class="logo" src="{{ logo_path }}">{% endif %}
      <h1>{{ business.name }}</h1>
      <div>{{ business.address or "" }}</div>
      <div>GSTIN: {{ business.gstin or "-" }}</div>
    </div>
    <div>
      <div><strong>Invoice No:</strong> {{ invoice.invoice_no }}</div>
      <div><strong>Date:</strong> {{ invoice.invoice_date }}</div>
      {% if invoice.due_date %}<div><strong>Due Date:</strong> {{ invoice.due_date }}</div>{% endif %}
    </div>
  </div>

  <h2>Bill To</h2>
  <div>{{ customer.name }}</div>
  <div>{{ customer.address or "" }}</div>
  <div>GSTIN/PAN: {{ customer.gstin_pan or "-" }}</div>
  <div>Place of Supply: {{ customer.place_of_supply or "-" }}</div>

  <table>
    <thead>
      <tr>
        <th>Sr</th><th>Product</th><th>HSN/SAC</th><th>Qty</th><th>UOM</th>
        <th>Price</th><th>Discount</th><th>GST %</th><th>Total</th>
      </tr>
    </thead>
    <tbody>
      {% for item in line_items %}
      <tr>
        <td>{{ item.sr_no }}</td>
        <td>{{ item.product_name }}</td>
        <td>{{ item.hsn_sac or "" }}</td>
        <td>{{ item.qty }}</td>
        <td>{{ item.uom or "" }}</td>
        <td>{{ item.price }}</td>
        <td>{{ item.discount }}</td>
        <td>{{ item.gst_rate }}</td>
        <td>{{ item.line_total }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <table class="totals">
    <tr><td>Taxable Total</td><td>{{ invoice.taxable_total }}</td></tr>
    <tr><td>Total Tax</td><td>{{ invoice.tax_total }}</td></tr>
    <tr class="grand-total"><td>Grand Total</td><td>{{ invoice.grand_total }}</td></tr>
  </table>
  <div>Amount in words: {{ amount_in_words }}</div>

  {% if business.signature_url %}
  <div>
    <img class="signature" src="{{ signature_path }}">
    <div>Authorized Signatory</div>
  </div>
  {% endif %}
</body>
</html>
```

- [ ] **Step 5: Write `app/services/pdf.py`**

```python
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.config import get_settings
from app.models import Invoice
from app.services.num2words_inr import amount_in_words

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


def render_invoice_pdf(invoice: Invoice) -> bytes:
    settings = get_settings()
    upload_root = Path(settings.upload_dir).resolve()

    # logo_url/signature_url already carry the correct extension (Task 5's
    # save_upload accepts .png/.jpg/.jpeg) — resolve them from upload_root
    # rather than hardcoding an extension.
    template = _env.get_template("invoice.html")
    html = template.render(
        invoice=invoice,
        business=invoice.business,
        customer=invoice.customer,
        line_items=invoice.line_items,
        amount_in_words=amount_in_words(invoice.grand_total),
        logo_path=f"file://{upload_root}{invoice.business.logo_url}" if invoice.business.logo_url else None,
        signature_path=f"file://{upload_root}{invoice.business.signature_url}" if invoice.business.signature_url else None,
    )
    return HTML(string=html).write_pdf()
```

- [ ] **Step 6: Add the download endpoint to `app/routers/invoices.py`**

```python
# add to backend/app/routers/invoices.py
from fastapi import Response

from app.services.pdf import render_invoice_pdf


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    invoice = _get_owned_or_404(db, business, invoice_id)
    pdf_bytes = render_invoice_pdf(invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_no}.pdf"'},
    )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_invoice_pdf.py -v`
Expected: PASS

- [ ] **Step 8: Run the full backend test suite**

Run: `cd backend && .venv/bin/pytest -v`
Expected: all tests PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models.py backend/app/templates backend/app/services/pdf.py backend/app/routers/invoices.py backend/tests/test_invoice_pdf.py
git commit -m "feat(backend): add PDF rendering and invoice download endpoint"
```

---

## Frontend tasks

The spec explicitly scopes frontend testing to manual verification, not automated tests (see "Testing" section of the design doc). Frontend tasks below follow implement → run dev server → manually verify in browser, instead of the red/green TDD cycle used for the backend.

## Task 12: Frontend scaffold

**Files:**
- Create: `frontend/` (via Vite scaffold)
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/store/authStore.ts`
- Create: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/.env.example`

**Interfaces:**
- Produces: `frontend/src/api/client.ts` exports `apiClient` (axios instance, `baseURL` from `import.meta.env.VITE_API_URL`, request interceptor attaching `Authorization: Bearer <token>` from `authStore`)
- Produces: `frontend/src/store/authStore.ts` exports `useAuthStore` (zustand store: `token: string | null`, `setToken(token: string | null): void`, persisted to `localStorage` under key `"billing-buddy-token"`)
- Produces: `frontend/src/App.tsx` — router shell with routes `/login`, `/signup`, `/` (protected, redirects to `/login` if no token)

- [ ] **Step 1: Scaffold the Vite project**

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install axios @tanstack/react-query zustand react-router-dom react-hook-form
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 2: Configure Tailwind**

```js
// frontend/tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

```css
/* replace contents of frontend/src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 3: Write `.env.example`**

```
VITE_API_URL=http://localhost:8000
```

Copy it: `cp .env.example .env`

- [ ] **Step 4: Write `src/store/authStore.ts`**

```typescript
import { create } from "zustand";

const STORAGE_KEY = "billing-buddy-token";

interface AuthState {
  token: string | null;
  setToken: (token: string | null) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem(STORAGE_KEY),
  setToken: (token) => {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else localStorage.removeItem(STORAGE_KEY);
    set({ token });
  },
}));
```

- [ ] **Step 5: Write `src/api/client.ts`**

```typescript
import axios from "axios";

import { useAuthStore } from "../store/authStore";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
```

- [ ] **Step 6: Write `src/App.tsx` with a protected-route shell**

```tsx
import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";

import { useAuthStore } from "./store/authStore";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

function Dashboard() {
  return <div className="p-6">Dashboard placeholder — invoice list goes here (Task 18).</div>;
}

function Login() {
  return <div className="p-6">Login placeholder (Task 13).</div>;
}

function Signup() {
  return <div className="p-6">Signup placeholder (Task 13).</div>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
```

- [ ] **Step 7: Wire up React Query in `src/main.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./index.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 8: Verify manually**

Run: `cd frontend && npm run dev`
Expected: dev server starts on `http://localhost:5173`; visiting `/` redirects to `/login` (no token yet); visiting `/login` and `/signup` show their placeholder text.

- [ ] **Step 9: Commit**

```bash
git add frontend
git commit -m "feat(frontend): scaffold Vite/React/TS app with routing, auth store, API client"
```

---

## Task 13: Auth pages (signup, login)

**Files:**
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/SignupPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 12), `useAuthStore` (Task 12)
- Produces: `frontend/src/api/auth.ts` exports `signup(body: {business_name: string; email: string; password: string}): Promise<{access_token: string}>` and `login(body: {email: string; password: string}): Promise<{access_token: string}>`, both `POST`ing to the backend and returning `response.data`.

- [ ] **Step 1: Write `src/api/auth.ts`**

```typescript
import { apiClient } from "./client";

interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function signup(body: {
  business_name: string;
  email: string;
  password: string;
}): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/signup", body);
  return data;
}

export async function login(body: { email: string; password: string }): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/login", body);
  return data;
}
```

- [ ] **Step 2: Write `src/pages/LoginPage.tsx`**

```tsx
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

import { login } from "../api/auth";
import { useAuthStore } from "../store/authStore";

interface FormValues {
  email: string;
  password: string;
}

export default function LoginPage() {
  const navigate = useNavigate();
  const setToken = useAuthStore((s) => s.setToken);
  const { register, handleSubmit } = useForm<FormValues>();

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: (data) => {
      setToken(data.access_token);
      navigate("/");
    },
  });

  return (
    <div className="max-w-sm mx-auto mt-20 p-6 border rounded">
      <h1 className="text-xl font-semibold mb-4">Log in</h1>
      <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-3">
        <input
          {...register("email", { required: true })}
          type="email"
          placeholder="Email"
          className="w-full border rounded px-3 py-2"
        />
        <input
          {...register("password", { required: true })}
          type="password"
          placeholder="Password"
          className="w-full border rounded px-3 py-2"
        />
        {mutation.isError && (
          <p className="text-red-600 text-sm">Invalid email or password.</p>
        )}
        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full bg-green-600 text-white rounded px-3 py-2"
        >
          {mutation.isPending ? "Logging in..." : "Log in"}
        </button>
      </form>
      <p className="text-sm mt-3">
        No account? <Link to="/signup" className="text-green-700 underline">Sign up</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Write `src/pages/SignupPage.tsx`**

```tsx
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

import { signup } from "../api/auth";
import { useAuthStore } from "../store/authStore";

interface FormValues {
  business_name: string;
  email: string;
  password: string;
}

export default function SignupPage() {
  const navigate = useNavigate();
  const setToken = useAuthStore((s) => s.setToken);
  const { register, handleSubmit } = useForm<FormValues>();

  const mutation = useMutation({
    mutationFn: signup,
    onSuccess: (data) => {
      setToken(data.access_token);
      navigate("/");
    },
  });

  return (
    <div className="max-w-sm mx-auto mt-20 p-6 border rounded">
      <h1 className="text-xl font-semibold mb-4">Create your business account</h1>
      <form onSubmit={handleSubmit((values) => mutation.mutate(values))} className="space-y-3">
        <input
          {...register("business_name", { required: true })}
          placeholder="Business name"
          className="w-full border rounded px-3 py-2"
        />
        <input
          {...register("email", { required: true })}
          type="email"
          placeholder="Email"
          className="w-full border rounded px-3 py-2"
        />
        <input
          {...register("password", { required: true, minLength: 8 })}
          type="password"
          placeholder="Password (min 8 chars)"
          className="w-full border rounded px-3 py-2"
        />
        {mutation.isError && (
          <p className="text-red-600 text-sm">Could not sign up — email may already be registered.</p>
        )}
        <button
          type="submit"
          disabled={mutation.isPending}
          className="w-full bg-green-600 text-white rounded px-3 py-2"
        >
          {mutation.isPending ? "Creating..." : "Sign up"}
        </button>
      </form>
      <p className="text-sm mt-3">
        Already have an account? <Link to="/login" className="text-green-700 underline">Log in</Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Wire the pages into `src/App.tsx`**

```tsx
// replace the placeholder Login/Signup components and their imports in
// frontend/src/App.tsx with:
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";

// and update the routes:
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
```

- [ ] **Step 5: Verify manually**

Run backend (`cd backend && .venv/bin/uvicorn app.main:app --reload`) and frontend (`cd frontend && npm run dev`) together. Visit `http://localhost:5173/signup`, submit a new business/email/password, confirm redirect to `/` and that `localStorage` has a `billing-buddy-token` entry. Log out by clearing `localStorage`, then log back in via `/login` with the same credentials and confirm redirect to `/`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/auth.ts frontend/src/pages/LoginPage.tsx frontend/src/pages/SignupPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add signup and login pages"
```

---

## Task 14: Business profile page (incl. logo/signature upload)

**Files:**
- Create: `frontend/src/api/business.ts`
- Create: `frontend/src/pages/BusinessProfilePage.tsx`
- Create: `frontend/src/components/NavBar.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 12)
- Produces: `frontend/src/api/business.ts` exports `getBusiness(): Promise<Business>`, `updateBusiness(body: Partial<Business>): Promise<Business>`, `uploadLogo(file: File): Promise<Business>`, `uploadSignature(file: File): Promise<Business>`; `Business` type: `{id, name, gstin, address, state, phone, email, logo_url, signature_url, invoice_prefix, invoice_postfix}`
- Produces: `frontend/src/components/NavBar.tsx` — top nav with links to Dashboard, Business Profile, Bank Accounts, log-out button (clears `authStore` token)

- [ ] **Step 1: Write `src/api/business.ts`**

```typescript
import { apiClient } from "./client";

export interface Business {
  id: string;
  name: string;
  gstin: string | null;
  address: string | null;
  state: string | null;
  phone: string | null;
  email: string | null;
  logo_url: string | null;
  signature_url: string | null;
  invoice_prefix: string;
  invoice_postfix: string;
}

export async function getBusiness(): Promise<Business> {
  const { data } = await apiClient.get<Business>("/business");
  return data;
}

export async function updateBusiness(body: Partial<Business>): Promise<Business> {
  const { data } = await apiClient.put<Business>("/business", body);
  return data;
}

async function uploadFile(path: string, file: File): Promise<Business> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<Business>(path, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export const uploadLogo = (file: File) => uploadFile("/business/logo", file);
export const uploadSignature = (file: File) => uploadFile("/business/signature", file);
```

- [ ] **Step 2: Write `src/components/NavBar.tsx`**

```tsx
import { Link, useNavigate } from "react-router-dom";

import { useAuthStore } from "../store/authStore";

export default function NavBar() {
  const navigate = useNavigate();
  const setToken = useAuthStore((s) => s.setToken);

  return (
    <nav className="border-b px-6 py-3 flex gap-6 items-center bg-white">
      <Link to="/" className="font-semibold">Billing Buddy</Link>
      <Link to="/">Invoices</Link>
      <Link to="/business">Business Profile</Link>
      <Link to="/bank-accounts">Bank Accounts</Link>
      <button
        className="ml-auto text-sm text-gray-600"
        onClick={() => {
          setToken(null);
          navigate("/login");
        }}
      >
        Log out
      </button>
    </nav>
  );
}
```

- [ ] **Step 3: Write `src/pages/BusinessProfilePage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Business, getBusiness, updateBusiness, uploadLogo, uploadSignature } from "../api/business";
import NavBar from "../components/NavBar";

export default function BusinessProfilePage() {
  const queryClient = useQueryClient();
  const { data: business } = useQuery({ queryKey: ["business"], queryFn: getBusiness });
  const { register, handleSubmit, reset } = useForm<Partial<Business>>();

  useEffect(() => {
    if (business) reset(business);
  }, [business, reset]);

  const updateMutation = useMutation({
    mutationFn: updateBusiness,
    onSuccess: (data) => queryClient.setQueryData(["business"], data),
  });

  const logoMutation = useMutation({
    mutationFn: uploadLogo,
    onSuccess: (data) => queryClient.setQueryData(["business"], data),
  });

  const signatureMutation = useMutation({
    mutationFn: uploadSignature,
    onSuccess: (data) => queryClient.setQueryData(["business"], data),
  });

  if (!business) return <div className="p-6">Loading...</div>;

  return (
    <div>
      <NavBar />
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <h1 className="text-xl font-semibold">Business Profile</h1>

        <form onSubmit={handleSubmit((values) => updateMutation.mutate(values))} className="space-y-3">
          <input {...register("name")} placeholder="Business name" className="w-full border rounded px-3 py-2" />
          <input {...register("gstin")} placeholder="GSTIN" className="w-full border rounded px-3 py-2" />
          <textarea {...register("address")} placeholder="Address" className="w-full border rounded px-3 py-2" />
          <input {...register("state")} placeholder="State" className="w-full border rounded px-3 py-2" />
          <input {...register("phone")} placeholder="Phone" className="w-full border rounded px-3 py-2" />
          <input {...register("email")} placeholder="Email" className="w-full border rounded px-3 py-2" />
          <input {...register("invoice_prefix")} placeholder="Invoice prefix (e.g. INV-)" className="w-full border rounded px-3 py-2" />
          <input {...register("invoice_postfix")} placeholder="Invoice postfix (e.g. /26-27)" className="w-full border rounded px-3 py-2" />
          <button type="submit" className="bg-green-600 text-white rounded px-4 py-2">
            {updateMutation.isPending ? "Saving..." : "Save"}
          </button>
        </form>

        <div>
          <h2 className="font-semibold mb-2">Logo</h2>
          {business.logo_url && (
            <img src={`${import.meta.env.VITE_API_URL}${business.logo_url}`} className="h-16 mb-2" />
          )}
          <input
            type="file"
            accept="image/png,image/jpeg"
            onChange={(e) => e.target.files?.[0] && logoMutation.mutate(e.target.files[0])}
          />
        </div>

        <div>
          <h2 className="font-semibold mb-2">Signature</h2>
          {business.signature_url && (
            <img src={`${import.meta.env.VITE_API_URL}${business.signature_url}`} className="h-12 mb-2" />
          )}
          <input
            type="file"
            accept="image/png,image/jpeg"
            onChange={(e) => e.target.files?.[0] && signatureMutation.mutate(e.target.files[0])}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the route into `src/App.tsx`**

```tsx
// add to frontend/src/App.tsx
import BusinessProfilePage from "./pages/BusinessProfilePage";

// add inside <Routes>, alongside the other <Route>s
        <Route
          path="/business"
          element={
            <ProtectedRoute>
              <BusinessProfilePage />
            </ProtectedRoute>
          }
        />
```

- [ ] **Step 5: Verify manually**

With both servers running, log in, visit `/business`, fill in GSTIN/address/state, save, refresh the page and confirm values persisted. Upload a small PNG as logo and as signature; confirm both previews render.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/business.ts frontend/src/pages/BusinessProfilePage.tsx frontend/src/components/NavBar.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add business profile page with logo/signature upload"
```

---

## Task 15: Bank accounts page

**Files:**
- Create: `frontend/src/api/bankAccounts.ts`
- Create: `frontend/src/pages/BankAccountsPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 12)
- Produces: `frontend/src/api/bankAccounts.ts` exports `listBankAccounts(): Promise<BankAccount[]>`, `createBankAccount(body): Promise<BankAccount>`, `deleteBankAccount(id: string): Promise<void>`; `BankAccount` type: `{id, bank_name, account_no, ifsc, is_default}`

- [ ] **Step 1: Write `src/api/bankAccounts.ts`**

```typescript
import { apiClient } from "./client";

export interface BankAccount {
  id: string;
  bank_name: string;
  account_no: string;
  ifsc: string;
  is_default: boolean;
}

export async function listBankAccounts(): Promise<BankAccount[]> {
  const { data } = await apiClient.get<BankAccount[]>("/bank-accounts");
  return data;
}

export async function createBankAccount(
  body: Omit<BankAccount, "id">,
): Promise<BankAccount> {
  const { data } = await apiClient.post<BankAccount>("/bank-accounts", body);
  return data;
}

export async function deleteBankAccount(id: string): Promise<void> {
  await apiClient.delete(`/bank-accounts/${id}`);
}
```

- [ ] **Step 2: Write `src/pages/BankAccountsPage.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";

import { BankAccount, createBankAccount, deleteBankAccount, listBankAccounts } from "../api/bankAccounts";
import NavBar from "../components/NavBar";

export default function BankAccountsPage() {
  const queryClient = useQueryClient();
  const { data: accounts = [] } = useQuery({ queryKey: ["bank-accounts"], queryFn: listBankAccounts });
  const { register, handleSubmit, reset } = useForm<Omit<BankAccount, "id">>({
    defaultValues: { is_default: false },
  });

  const createMutation = useMutation({
    mutationFn: createBankAccount,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bank-accounts"] });
      reset();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteBankAccount,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bank-accounts"] }),
  });

  return (
    <div>
      <NavBar />
      <div className="max-w-2xl mx-auto p-6 space-y-6">
        <h1 className="text-xl font-semibold">Bank Accounts</h1>

        <ul className="divide-y border rounded">
          {accounts.map((a) => (
            <li key={a.id} className="p-3 flex justify-between items-center">
              <span>{a.bank_name} — {a.account_no} ({a.ifsc}){a.is_default ? " · default" : ""}</span>
              <button
                className="text-red-600 text-sm"
                onClick={() => deleteMutation.mutate(a.id)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>

        <form
          onSubmit={handleSubmit((values) => createMutation.mutate(values))}
          className="space-y-3"
        >
          <input {...register("bank_name", { required: true })} placeholder="Bank name" className="w-full border rounded px-3 py-2" />
          <input {...register("account_no", { required: true })} placeholder="Account number" className="w-full border rounded px-3 py-2" />
          <input {...register("ifsc", { required: true })} placeholder="IFSC" className="w-full border rounded px-3 py-2" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...register("is_default")} /> Set as default
          </label>
          <button type="submit" className="bg-green-600 text-white rounded px-4 py-2">
            Add bank account
          </button>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire the route into `src/App.tsx`**

```tsx
// add to frontend/src/App.tsx
import BankAccountsPage from "./pages/BankAccountsPage";

        <Route
          path="/bank-accounts"
          element={
            <ProtectedRoute>
              <BankAccountsPage />
            </ProtectedRoute>
          }
        />
```

- [ ] **Step 4: Verify manually**

Visit `/bank-accounts`, add "HDFC Bank" / an account number / IFSC, confirm it appears in the list, then delete it and confirm it disappears.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/bankAccounts.ts frontend/src/pages/BankAccountsPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add bank accounts management page"
```

---

## Task 16: Customer API client and autocomplete component

**Files:**
- Create: `frontend/src/api/customers.ts`
- Create: `frontend/src/components/CustomerAutocomplete.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 12)
- Produces: `frontend/src/api/customers.ts` exports `searchCustomers(q: string): Promise<Customer[]>`, `createCustomer(body): Promise<Customer>`; `Customer` type: `{id, name, address, contact_person, phone, gstin_pan, place_of_supply, reverse_charge, ship_to}`
- Produces: `frontend/src/components/CustomerAutocomplete.tsx` — props `{value: Customer | null; onChange: (customer: Customer) => void}`. Debounced text input (300ms) that searches customers by name; selecting a result calls `onChange`; typing a name with no match shows a "Create new customer" option that calls `createCustomer({name: query})` then `onChange`s the result.

- [ ] **Step 1: Write `src/api/customers.ts`**

```typescript
import { apiClient } from "./client";

export interface Customer {
  id: string;
  name: string;
  address: string | null;
  contact_person: string | null;
  phone: string | null;
  gstin_pan: string | null;
  place_of_supply: string | null;
  reverse_charge: boolean;
  ship_to: string | null;
}

export async function searchCustomers(q: string): Promise<Customer[]> {
  const { data } = await apiClient.get<Customer[]>("/customers", { params: { q } });
  return data;
}

export async function createCustomer(body: { name: string }): Promise<Customer> {
  const { data } = await apiClient.post<Customer>("/customers", body);
  return data;
}
```

- [ ] **Step 2: Write `src/components/CustomerAutocomplete.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Customer, createCustomer, searchCustomers } from "../api/customers";

interface Props {
  value: Customer | null;
  onChange: (customer: Customer) => void;
}

export default function CustomerAutocomplete({ value, onChange }: Props) {
  const [query, setQuery] = useState(value?.name ?? "");
  const [debounced, setDebounced] = useState(query);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data: results = [] } = useQuery({
    queryKey: ["customers", debounced],
    queryFn: () => searchCustomers(debounced),
    enabled: debounced.length > 0 && open,
  });

  const exactMatch = results.some((r) => r.name.toLowerCase() === query.toLowerCase());

  async function handleCreate() {
    const customer = await createCustomer({ name: query });
    onChange(customer);
    setOpen(false);
  }

  function handleSelect(customer: Customer) {
    setQuery(customer.name);
    onChange(customer);
    setOpen(false);
  }

  return (
    <div className="relative">
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="M/S — customer name"
        className="w-full border rounded px-3 py-2"
      />
      {open && debounced && (
        <ul className="absolute z-10 bg-white border rounded w-full mt-1 max-h-48 overflow-auto">
          {results.map((r) => (
            <li
              key={r.id}
              className="px-3 py-2 hover:bg-gray-100 cursor-pointer"
              onClick={() => handleSelect(r)}
            >
              {r.name}
            </li>
          ))}
          {!exactMatch && (
            <li
              className="px-3 py-2 hover:bg-gray-100 cursor-pointer text-green-700"
              onClick={handleCreate}
            >
              + Create "{query}"
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify manually**

This component is exercised end-to-end in Task 17 (invoice form) — defer manual verification to that task's step.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/customers.ts frontend/src/components/CustomerAutocomplete.tsx
git commit -m "feat(frontend): add customer API client and autocomplete component"
```

---

## Task 17: Sale invoice create/edit form

**Files:**
- Create: `frontend/src/api/invoices.ts`
- Create: `frontend/src/pages/InvoiceFormPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 12), `CustomerAutocomplete` (Task 16), `listBankAccounts` (Task 15)
- Produces: `frontend/src/api/invoices.ts` exports `createInvoice(body: InvoiceInput): Promise<Invoice>`, `getInvoice(id: string): Promise<Invoice>`, `updateInvoice(id: string, body: InvoiceInput): Promise<Invoice>`, matching the backend `InvoiceCreate`/`InvoiceRead` schemas from Task 10.
- Produces: route `/invoices/new` and `/invoices/:id/edit` both rendering `InvoiceFormPage`, which mirrors the reference screenshot's sections: Customer Information, Invoice Detail, Product Items table, Totals panel, Payment Type buttons.

- [ ] **Step 1: Write `src/api/invoices.ts`**

```typescript
import { apiClient } from "./client";

export interface InvoiceLineItemInput {
  product_name: string;
  hsn_sac: string | null;
  qty: string;
  uom: string | null;
  price: string;
  discount: string;
  gst_rate: string;
}

export interface InvoiceInput {
  customer_id: string;
  invoice_type: string | null;
  invoice_date: string;
  challan_no: string | null;
  challan_date: string | null;
  po_no: string | null;
  po_date: string | null;
  lr_no: string | null;
  eway_no: string | null;
  delivery_mode: string | null;
  due_date: string | null;
  bank_account_id: string | null;
  discount_type: "Rs" | "%";
  discount_value: string;
  tcs: string;
  round_off: boolean;
  terms_title: string | null;
  terms_detail: string | null;
  notes: string | null;
  remarks: string | null;
  payment_type: "credit" | "cash" | "cheque" | "online";
  line_items: InvoiceLineItemInput[];
}

export interface Invoice extends InvoiceInput {
  id: string;
  invoice_no: string;
  taxable_total: string;
  tax_total: string;
  grand_total: string;
  status: string;
  line_items: (InvoiceLineItemInput & { id: string; sr_no: number; line_total: string })[];
}

export async function createInvoice(body: InvoiceInput): Promise<Invoice> {
  const { data } = await apiClient.post<Invoice>("/invoices", body);
  return data;
}

export async function getInvoice(id: string): Promise<Invoice> {
  const { data } = await apiClient.get<Invoice>(`/invoices/${id}`);
  return data;
}

export async function updateInvoice(id: string, body: InvoiceInput): Promise<Invoice> {
  const { data } = await apiClient.put<Invoice>(`/invoices/${id}`, body);
  return data;
}
```

- [ ] **Step 2: Write `src/pages/InvoiceFormPage.tsx`**

```tsx
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useNavigate, useParams } from "react-router-dom";

import { listBankAccounts } from "../api/bankAccounts";
import { Customer } from "../api/customers";
import { InvoiceInput, createInvoice, getInvoice, updateInvoice } from "../api/invoices";
import CustomerAutocomplete from "../components/CustomerAutocomplete";
import NavBar from "../components/NavBar";

const emptyLineItem = {
  product_name: "",
  hsn_sac: "",
  qty: "1",
  uom: "",
  price: "0",
  discount: "0",
  gst_rate: "0",
};

const defaultValues: InvoiceInput = {
  customer_id: "",
  invoice_type: null,
  invoice_date: new Date().toISOString().slice(0, 10),
  challan_no: null,
  challan_date: null,
  po_no: null,
  po_date: null,
  lr_no: null,
  eway_no: null,
  delivery_mode: null,
  due_date: null,
  bank_account_id: null,
  discount_type: "Rs",
  discount_value: "0",
  tcs: "0",
  round_off: true,
  terms_title: null,
  terms_detail: null,
  notes: null,
  remarks: null,
  payment_type: "credit",
  line_items: [emptyLineItem],
};

export default function InvoiceFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();

  const { data: bankAccounts = [] } = useQuery({ queryKey: ["bank-accounts"], queryFn: listBankAccounts });
  const { data: existingInvoice } = useQuery({
    queryKey: ["invoice", id],
    queryFn: () => getInvoice(id as string),
    enabled: isEdit,
  });

  const { register, control, handleSubmit, reset, watch } = useForm<InvoiceInput>({ defaultValues });
  const { fields, append, remove } = useFieldArray({ control, name: "line_items" });

  useEffect(() => {
    if (existingInvoice) reset(existingInvoice);
  }, [existingInvoice, reset]);

  const saveMutation = useMutation({
    mutationFn: (body: InvoiceInput) => (isEdit ? updateInvoice(id as string, body) : createInvoice(body)),
    onSuccess: (invoice) => navigate(`/invoices/${invoice.id}/edit`),
  });

  const lineItems = watch("line_items");

  function handleCustomerChange(customer: Customer) {
    reset((current) => ({
      ...current,
      customer_id: customer.id,
    }));
  }

  return (
    <div>
      <NavBar />
      <form
        onSubmit={handleSubmit((values) => saveMutation.mutate(values))}
        className="max-w-5xl mx-auto p-6 space-y-6"
      >
        <h1 className="text-xl font-semibold">
          {isEdit ? `Edit Invoice ${existingInvoice?.invoice_no ?? ""}` : "Create Sale Invoice"}
        </h1>

        <section className="grid grid-cols-2 gap-6">
          <div className="border rounded p-4 space-y-3">
            <h2 className="font-semibold">Customer Information</h2>
            <CustomerAutocomplete
              value={null}
              onChange={handleCustomerChange}
            />
          </div>

          <div className="border rounded p-4 space-y-3">
            <h2 className="font-semibold">Invoice Detail</h2>
            <input {...register("invoice_date", { required: true })} type="date" className="w-full border rounded px-3 py-2" />
            <input {...register("challan_no")} placeholder="Challan No." className="w-full border rounded px-3 py-2" />
            <input {...register("po_no")} placeholder="P.O. No." className="w-full border rounded px-3 py-2" />
            <input {...register("lr_no")} placeholder="L.R. No." className="w-full border rounded px-3 py-2" />
            <input {...register("eway_no")} placeholder="E-Way No." className="w-full border rounded px-3 py-2" />
          </div>
        </section>

        <section className="border rounded p-4">
          <h2 className="font-semibold mb-3">Product Items</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left border-b">
                <th>Product</th><th>HSN/SAC</th><th>Qty</th><th>UOM</th>
                <th>Price</th><th>Discount</th><th>GST %</th><th></th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field, index) => (
                <tr key={field.id}>
                  <td><input {...register(`line_items.${index}.product_name`)} className="border rounded px-2 py-1 w-full" /></td>
                  <td><input {...register(`line_items.${index}.hsn_sac`)} className="border rounded px-2 py-1 w-20" /></td>
                  <td><input {...register(`line_items.${index}.qty`)} className="border rounded px-2 py-1 w-16" /></td>
                  <td><input {...register(`line_items.${index}.uom`)} className="border rounded px-2 py-1 w-16" /></td>
                  <td><input {...register(`line_items.${index}.price`)} className="border rounded px-2 py-1 w-24" /></td>
                  <td><input {...register(`line_items.${index}.discount`)} className="border rounded px-2 py-1 w-20" /></td>
                  <td>
                    <select {...register(`line_items.${index}.gst_rate`)} className="border rounded px-2 py-1">
                      <option value="0">0%</option>
                      <option value="5">5%</option>
                      <option value="12">12%</option>
                      <option value="18">18%</option>
                      <option value="28">28%</option>
                    </select>
                  </td>
                  <td>
                    <button type="button" onClick={() => remove(index)} className="text-red-600">×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="button"
            onClick={() => append(emptyLineItem)}
            className="mt-2 text-sm text-green-700"
          >
            + Add item
          </button>
        </section>

        <section className="grid grid-cols-2 gap-6">
          <div className="border rounded p-4 space-y-3">
            <select {...register("bank_account_id")} className="w-full border rounded px-3 py-2">
              <option value="">Select bank</option>
              {bankAccounts.map((b) => (
                <option key={b.id} value={b.id}>{b.bank_name} ({b.account_no})</option>
              ))}
            </select>
            <input {...register("due_date")} type="date" className="w-full border rounded px-3 py-2" />
            <textarea {...register("terms_detail")} placeholder="Terms & conditions" className="w-full border rounded px-3 py-2" />
          </div>

          <div className="border rounded p-4 space-y-2">
            <label className="flex justify-between"><span>Discount</span>
              <span>
                <input {...register("discount_value")} className="border rounded px-2 py-1 w-20" />
                <select {...register("discount_type")} className="border rounded px-2 py-1 ml-2">
                  <option value="Rs">Rs</option>
                  <option value="%">%</option>
                </select>
              </span>
            </label>
            <label className="flex justify-between"><span>TCS</span>
              <input {...register("tcs")} className="border rounded px-2 py-1 w-20" />
            </label>
            <label className="flex justify-between"><span>Round Off</span>
              <input type="checkbox" {...register("round_off")} />
            </label>
            <div className="flex gap-2 pt-2">
              {(["credit", "cash", "cheque", "online"] as const).map((type) => (
                <label key={type} className="flex items-center gap-1 text-sm">
                  <input type="radio" value={type} {...register("payment_type")} /> {type}
                </label>
              ))}
            </div>
          </div>
        </section>

        <button
          type="submit"
          disabled={saveMutation.isPending}
          className="bg-green-600 text-white rounded px-6 py-2"
        >
          {saveMutation.isPending ? "Saving..." : "Save"}
        </button>
        {isEdit && existingInvoice && (
          <a
            href={`${import.meta.env.VITE_API_URL}/invoices/${existingInvoice.id}/pdf`}
            className="ml-3 inline-block border rounded px-6 py-2"
          >
            Download PDF
          </a>
        )}
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Wire routes into `src/App.tsx`**

```tsx
// add to frontend/src/App.tsx
import InvoiceFormPage from "./pages/InvoiceFormPage";

        <Route path="/invoices/new" element={<ProtectedRoute><InvoiceFormPage /></ProtectedRoute>} />
        <Route path="/invoices/:id/edit" element={<ProtectedRoute><InvoiceFormPage /></ProtectedRoute>} />
```

- [ ] **Step 4: Verify manually**

Visit `/invoices/new`, type a new customer name into Customer Information and select "+ Create", fill in one line item (price 500, qty 2, GST 18%), save. Confirm redirect to the edit URL, that a "Download PDF" link appears, and that clicking it downloads a PDF starting with the business name and the line item.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/invoices.ts frontend/src/pages/InvoiceFormPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add sale invoice create/edit form"
```

---

## Task 18: Invoice list page (dashboard) and PDF download

**Files:**
- Modify: `frontend/src/api/invoices.ts`
- Create: `frontend/src/pages/InvoiceListPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `apiClient` (Task 12), `Invoice` type (Task 17)
- Produces: `listInvoices(): Promise<InvoiceListItem[]>` added to `frontend/src/api/invoices.ts`; `InvoiceListItem` type: `{id, invoice_no, invoice_date, grand_total, status}`
- Produces: `frontend/src/pages/InvoiceListPage.tsx` — replaces the `Dashboard` placeholder in `App.tsx`, table of invoices with a "Download" link per row and a "New Invoice" button linking to `/invoices/new`

- [ ] **Step 1: Add `listInvoices` to `src/api/invoices.ts`**

```typescript
// append to frontend/src/api/invoices.ts
export interface InvoiceListItem {
  id: string;
  invoice_no: string;
  invoice_date: string;
  grand_total: string;
  status: string;
}

export async function listInvoices(): Promise<InvoiceListItem[]> {
  const { data } = await apiClient.get<InvoiceListItem[]>("/invoices");
  return data;
}
```

- [ ] **Step 2: Write `src/pages/InvoiceListPage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listInvoices } from "../api/invoices";
import NavBar from "../components/NavBar";

export default function InvoiceListPage() {
  const { data: invoices = [] } = useQuery({ queryKey: ["invoices"], queryFn: listInvoices });

  return (
    <div>
      <NavBar />
      <div className="max-w-4xl mx-auto p-6 space-y-4">
        <div className="flex justify-between items-center">
          <h1 className="text-xl font-semibold">Sale Invoices</h1>
          <Link to="/invoices/new" className="bg-green-600 text-white rounded px-4 py-2">
            + Create Another Invoice
          </Link>
        </div>

        <table className="w-full border rounded">
          <thead>
            <tr className="text-left border-b bg-gray-50">
              <th className="p-2">Invoice No</th>
              <th className="p-2">Date</th>
              <th className="p-2">Grand Total</th>
              <th className="p-2">Status</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id} className="border-b">
                <td className="p-2">
                  <Link to={`/invoices/${inv.id}/edit`} className="text-green-700 underline">
                    {inv.invoice_no}
                  </Link>
                </td>
                <td className="p-2">{inv.invoice_date}</td>
                <td className="p-2">{inv.grand_total}</td>
                <td className="p-2">{inv.status}</td>
                <td className="p-2">
                  <a
                    href={`${import.meta.env.VITE_API_URL}/invoices/${inv.id}/pdf`}
                    className="text-sm border rounded px-2 py-1"
                  >
                    Download
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire it into `src/App.tsx`, replacing the `Dashboard` placeholder**

```tsx
// in frontend/src/App.tsx: remove the inline `Dashboard` function and its
// usage, import the real page instead
import InvoiceListPage from "./pages/InvoiceListPage";

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <InvoiceListPage />
            </ProtectedRoute>
          }
        />
```

- [ ] **Step 4: Verify manually — full end-to-end walkthrough**

1. `cd backend && .venv/bin/uvicorn app.main:app --reload` and `cd frontend && npm run dev` running together.
2. Sign up a new business at `/signup`.
3. Go to `/business`, set state to "Gujarat", upload a logo and a signature.
4. Go to `/bank-accounts`, add "HDFC Bank" with an account number and IFSC.
5. Go to `/` (invoice list, empty), click "+ Create Another Invoice".
6. Create a customer "Acme Traders" inline with place of supply "Gujarat" (same state → expect CGST+SGST split), add a line item (qty 2, price 500, GST 18%), pick the bank account, save.
7. Confirm the invoice list shows the new invoice with the correct grand total (₹1180).
8. Click "Download" — confirm a PDF downloads showing the business logo, customer, line item, and totals matching the on-screen values.
9. Repeat with a customer whose place of supply differs from the business state (e.g. "Maharashtra") and confirm the PDF/totals reflect IGST instead of CGST+SGST (visually check the `tax_total` matches; the UI doesn't currently break out CGST/SGST/IGST as separate columns — that's fine for v1, `tax_total` is what's user-facing and it's already verified correct by the backend unit tests in Task 8).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/invoices.ts frontend/src/pages/InvoiceListPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add invoice list page with PDF download"
```
