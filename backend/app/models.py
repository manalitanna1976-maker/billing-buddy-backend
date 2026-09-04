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
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    customer: Mapped["Customer"] = relationship()
    business: Mapped["Business"] = relationship()


class RevokedToken(Base):
    """A JWT id (jti) that has been logged out and must be rejected until it
    would have expired on its own. Shared across web and worker processes."""

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class RateLimitEvent(Base):
    """One recorded failed-login (or, in future, other rate-limited) attempt.
    Rows are counted within a sliding window per `bucket_key`. Shared across
    web and worker processes. Growth is bounded by a global time-based prune
    on every write (see app/rate_limit.py) -- no scheduler needed."""

    __tablename__ = "rate_limit_events"
    __table_args__ = (
        Index("ix_rate_limit_events_bucket_key_occurred_at", "bucket_key", "occurred_at"),
        Index("ix_rate_limit_events_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    bucket_key: Mapped[str] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
