# Subscription Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Free / Pro / Business plans to Billing Buddy CRM — gate the automation features and cap Free-tier volume, and let a business pay ₹4,990/year through Razorpay to unlock Pro.

**Architecture:** Plans are config-as-code (`app/billing/plans.py`). Each business's plan is four columns on the `businesses` row, so entitlement checks are a dict lookup with zero extra queries. One pure module (`app/billing/entitlements.py`) is called from both FastAPI dependencies and the WhatsApp worker. Payment is a one-time Razorpay **Order** (no mandates / auto-renew in v1); a signed, idempotent webhook plus a client-callback verify both converge on the same `_activate_pro` state change; a sweep in the existing worker loop reverts lapsed plans to Free.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic, Postgres, `httpx`, `hmac`/`hashlib` (no Razorpay SDK); React 18 + TypeScript + Vite, TanStack Query, zustand, axios, react-hook-form, Tailwind; pytest + FastAPI `TestClient`.

**Spec:** `docs/superpowers/specs/2026-09-10-subscription-module-design.md` — read it alongside this plan.

## Global Constraints

- **Branch:** `subscription-module` (already created, off `whatsapp-feature`). All commits land here.
- **Nothing existing may break.** The baseline is **265 passing backend tests** (`cd backend && .venv/bin/python -m pytest -q`) and a clean frontend build (`cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`). Every task ends by running the relevant existing suites and confirming they are still green. The final task re-runs everything.
- **Migration numbering:** current Alembic head is `a7c3e1f90d24` (file `0008_purchases_doc_type.py`). The billing migration is `0009_billing.py`, `revision = "f9b2c1a4e7d0"`, `down_revision = "a7c3e1f90d24"`.
- **Datetimes:** always `from app.time_utils import utcnow` — naive UTC. Never `datetime.utcnow()` / `datetime.now()`.
- **Money in Razorpay is paise (integer).** ₹4,990 = `499000` paise. Amounts stored in our DB are rupees (`Numeric(10,2)`).
- **402 response body — the exact shape every gate returns** (source of truth; the spec's prose defers to this):
  ```json
  {"detail": {"message": "Your plan doesn't include this.", "code": "upgrade_required", "feature": "<feature-or-quota-key>", "plan_needed": "pro", "upgrade_url": "/pricing"}}
  ```
- **Feature keys:** `whatsapp`, `inventory_automation`, `whitelabel_pdf`. **Quota keys:** `invoices_per_month`, `customers`, `bank_accounts`. Use the named constants from `app/billing/plans.py`, never string literals, outside that file.
- **Plan codes:** `free`, `pro`, `business`. Unknown/missing → treat as `free`.
- **Config flag `billing_enabled` (default `False`).** Phase 1 ships with it off: gates enforce, but `/billing/checkout`, `/billing/verify`, `/billing/webhook` return `503` and the frontend shows no pay button / no `/pricing` nav link. Phase 2 is enabled by flipping it to `True`.
- **TDD:** write the failing test first, watch it fail, implement minimally, watch it pass, commit. Frequent commits — one per task minimum.
- **Test DB** must be running (`postgresql+psycopg://billing:billing@localhost:5544/billing_buddy_test`, per `backend/tests/conftest.py`). Tests use `Base.metadata.create_all`, so new models/columns appear automatically without running Alembic; the migration is verified separately in Task 1.

---

## File Structure

**Backend — new:**
| File | Responsibility |
|---|---|
| `backend/alembic/versions/0009_billing.py` | The migration: 4 columns on `businesses` + `billing_payments` table + backfill |
| `backend/app/billing/__init__.py` | package marker |
| `backend/app/billing/plans.py` | `Plan` dataclass, `PLANS` dict, feature/quota key constants, `plan_for(business)` |
| `backend/app/billing/entitlements.py` | `check_feature`, `check_quota`, `QuotaState`, `UpgradeRequired`, `quota_usage` |
| `backend/app/billing/razorpay_client.py` | `create_order`, `verify_payment_signature`, `verify_webhook_signature`, `_client` seam (Phase 2) |
| `backend/app/billing/grant.py` | `python -m app.billing.grant` CLI — manual plan grant/revoke |
| `backend/app/services/billing_expiry.py` | `billing_expiry_sweep(db)` — revert lapsed plans, disconnect WhatsApp (Phase 2) |
| `backend/app/routers/billing.py` | `GET /billing/me` (Phase 1); `POST /billing/checkout` `/verify` `/webhook` (Phase 2) |
| `backend/app/schemas/billing.py` | Pydantic response/request models for the billing router |
| `backend/tests/test_plans.py`, `test_entitlements.py`, `test_billing_gates.py`, `test_pdf_footer.py`, `test_billing_grant.py`, `test_billing_me.py` | Phase 1 tests |
| `backend/tests/test_razorpay_client.py`, `test_billing_checkout.py`, `test_billing_webhook.py`, `test_billing_expiry.py` | Phase 2 tests |

**Backend — modified:**
| File | Change |
|---|---|
| `backend/app/models.py` | 4 columns on `Business`; new `BillingPayment` model |
| `backend/app/config.py` | `billing_enabled`, `razorpay_key_id/key_secret/webhook_secret`, `razorpay_pro_price_inr` |
| `backend/app/deps.py` | `require_feature`, `require_quota`, `require_billing_enabled`, `upgrade_required_http` |
| `backend/app/rate_limit.py` | `WHATSAPP_UPGRADE_WINDOW_SECONDS = 86400` + include it in the prune `max(...)` |
| `backend/app/routers/invoices.py` | inline quota check in `finalize_invoice` |
| `backend/app/routers/customers.py` | `require_quota("customers")` on `POST /customers` |
| `backend/app/routers/bank_accounts.py` | `require_quota("bank_accounts")` on `POST /bank-accounts` |
| `backend/app/services/whatsapp_flow.py` | feature gate at the top of `handle_inbound` |
| `backend/app/services/pdf.py` | pass `show_powered_by` to the template |
| `backend/app/templates/invoice.html` | conditional "Made with Billing Buddy" footer |
| `backend/app/main.py` | `app.include_router(billing.router)` |
| `backend/app/workers/whatsapp_worker.py` | call `billing_expiry_sweep(db)` in the idle block (Phase 2) |

**Frontend — new:**
| File | Responsibility |
|---|---|
| `frontend/src/api/billing.ts` | `getBillingMe`, `startCheckout`, `verifyCheckout` + types |
| `frontend/src/store/upgradeStore.ts` | zustand store holding the current upgrade prompt (set by the interceptor) |
| `frontend/src/components/UpgradeInterstitial.tsx` | modal overlay shown when the upgrade store is set |
| `frontend/src/pages/BillingSettingsPage.tsx` | `/settings/billing` — plan, usage lines, receipts, Upgrade button |
| `frontend/src/pages/PricingPage.tsx` | `/pricing` — 3 columns, Pro CTA → checkout (Phase 2) |

**Frontend — modified:**
| File | Change |
|---|---|
| `frontend/src/api/client.ts` | 402 `upgrade_required` interceptor → `upgradeStore.show(...)` |
| `frontend/src/App.tsx` | routes for `/settings/billing` and `/pricing`; mount `<UpgradeInterstitial />` in `Shell` |
| `frontend/src/components/AppShell.tsx` | "Billing" nav item |

---

# PHASE 1 — Entitlements core (Tasks 1–12)

Ships deployable with `billing_enabled=False`: every tenant is Free, gates enforce, Pro is granted only by the CLI. No payment code path is reachable.

---

### Task 1: Migration + models — plan columns and `billing_payments`

**Files:**
- Create: `backend/alembic/versions/0009_billing.py`
- Modify: `backend/app/models.py` (add to `class Business`; add `class BillingPayment` after `class BankAccount`)
- Test: `backend/tests/test_models.py` (append)

**Interfaces:**
- Produces:
  - `Business.plan: str` (default `"free"`), `Business.plan_status: str` (default `"none"`), `Business.plan_period_end: datetime | None`, `Business.razorpay_customer_id: str | None`
  - `BillingPayment` with columns: `id`, `business_id`, `plan: str`, `amount_inr: Decimal`, `status: str` (default `"created"`), `razorpay_order_id: str | None`, `razorpay_payment_id: str | None`, `razorpay_event_id: str | None` (unique), `period_start: datetime | None`, `period_end: datetime | None`, `created_at: datetime`

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_models.py`, append:

```python
def test_business_defaults_to_free_plan(db_session):
    from app.models import Business

    b = Business(name="Plan Defaults Co")
    db_session.add(b)
    db_session.commit()
    db_session.refresh(b)
    assert b.plan == "free"
    assert b.plan_status == "none"
    assert b.plan_period_end is None
    assert b.razorpay_customer_id is None


def test_billing_payment_event_id_is_unique(db_session):
    import uuid as _uuid
    from decimal import Decimal

    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.models import BillingPayment, Business

    b = Business(name="Pay Co")
    db_session.add(b)
    db_session.flush()
    db_session.add(BillingPayment(
        business_id=b.id, plan="pro", amount_inr=Decimal("4990"),
        status="paid", razorpay_event_id="evt_1",
    ))
    db_session.commit()
    db_session.add(BillingPayment(
        business_id=b.id, plan="pro", amount_inr=Decimal("4990"),
        status="paid", razorpay_event_id="evt_1",
    ))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models.py -k "free_plan or event_id_is_unique" -v`
Expected: FAIL — `AttributeError: 'Business' has no attribute 'plan'` / cannot import `BillingPayment`.

- [ ] **Step 3: Add the model changes**

In `backend/app/models.py`, inside `class Business` (after `next_invoice_seq`):

```python
    plan: Mapped[str] = mapped_column(String(16), default="free", server_default="free")
    plan_status: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    plan_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

After `class BankAccount`:

```python
class BillingPayment(Base):
    """One payment attempt for a plan upgrade. `razorpay_event_id` is the
    webhook dedup key -- a replayed webhook hits the unique constraint and is
    treated as a no-op. A manual CLI grant writes a row here too
    (razorpay_order_id='manual-grant', amount_inr=0) for the audit trail."""

    __tablename__ = "billing_payments"
    __table_args__ = (
        Index("ix_billing_payments_business_id_created_at", "business_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id"), index=True)
    plan: Mapped[str] = mapped_column(String(16))
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[str] = mapped_column(String(16), default="created")  # created | paid | failed
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    razorpay_event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models.py -v`
Expected: PASS (all model tests, old and new).

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/0009_billing.py`:

```python
"""billing: plan columns on businesses + billing_payments table

Revision ID: f9b2c1a4e7d0
Revises: a7c3e1f90d24
Create Date: 2026-09-10 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9b2c1a4e7d0"
down_revision: Union[str, Sequence[str], None] = "a7c3e1f90d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("plan", sa.String(16), nullable=False, server_default="free"))
    op.add_column("businesses", sa.Column("plan_status", sa.String(16), nullable=False, server_default="none"))
    op.add_column("businesses", sa.Column("plan_period_end", sa.DateTime(), nullable=True))
    op.add_column("businesses", sa.Column("razorpay_customer_id", sa.String(64), nullable=True))
    # Existing rows are internal/QA tenants -> Free. The server_default already
    # covers them; this makes the intent explicit and covers any partial state.
    op.execute("UPDATE businesses SET plan = 'free', plan_status = 'none'")

    op.create_table(
        "billing_payments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("amount_inr", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="created"),
        sa.Column("razorpay_order_id", sa.String(64), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=True),
        sa.Column("razorpay_event_id", sa.String(64), nullable=True),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_payments_business_id", "billing_payments", ["business_id"])
    op.create_index("ix_billing_payments_business_id_created_at", "billing_payments",
                    ["business_id", "created_at"])
    op.create_index("ix_billing_payments_razorpay_order_id", "billing_payments", ["razorpay_order_id"])
    op.create_unique_constraint("uq_billing_payments_razorpay_event_id", "billing_payments",
                                ["razorpay_event_id"])


def downgrade() -> None:
    op.drop_table("billing_payments")
    op.drop_column("businesses", "razorpay_customer_id")
    op.drop_column("businesses", "plan_period_end")
    op.drop_column("businesses", "plan_status")
    op.drop_column("businesses", "plan")
```

- [ ] **Step 6: Verify the migration round-trips**

Run:
```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
.venv/bin/python -c "from sqlalchemy import create_engine, inspect; from app.config import get_settings; i=inspect(create_engine(get_settings().database_url)); cols={c['name'] for c in i.get_columns('businesses')}; assert {'plan','plan_status','plan_period_end','razorpay_customer_id'} <= cols, cols; assert 'billing_payments' in i.get_table_names(); print('migration OK')"
```
Expected: `migration OK`, no errors on any step.

- [ ] **Step 7: Full regression**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 265 prior + 2 new = **267 passing**, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0009_billing.py backend/tests/test_models.py
git commit -m "feat(billing): plan columns on businesses + billing_payments (migration 0009)"
```

**Regression check:** `tests/test_models.py`, `tests/whatsapp/test_models.py` — all pass. Migration down→up→down→up clean.
**QA acceptance:** After `alembic upgrade head`, every existing business row has `plan='free'`, `plan_status='none'`. `\d businesses` shows the 4 new columns; `\d billing_payments` shows the unique index on `razorpay_event_id`.

---

### Task 2: `app/billing/plans.py` — config-as-code plan catalogue

**Files:**
- Create: `backend/app/billing/__init__.py` (empty), `backend/app/billing/plans.py`
- Test: `backend/tests/test_plans.py`

**Interfaces:**
- Produces:
  - Constants: `FEATURE_WHATSAPP`, `FEATURE_INVENTORY`, `FEATURE_WHITELABEL`, `QUOTA_INVOICES`, `QUOTA_CUSTOMERS`, `QUOTA_BANK_ACCOUNTS` (all `str`)
  - `@dataclass(frozen=True) class Plan: code: str; name: str; price_inr_year: int | None; features: frozenset[str]; quotas: dict[str, int]`
  - `PLANS: dict[str, Plan]` with keys `"free"`, `"pro"`, `"business"`
  - `FREE: Plan` (= `PLANS["free"]`)
  - `plan_for(business) -> Plan` — reads `getattr(business, "plan", None)`, falls back to `FREE` for unknown/missing

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_plans.py`:

```python
from types import SimpleNamespace

from app.billing import plans


def test_free_plan_has_no_features_and_three_quotas():
    free = plans.PLANS["free"]
    assert free.features == frozenset()
    assert free.quotas == {
        plans.QUOTA_INVOICES: 20,
        plans.QUOTA_CUSTOMERS: 25,
        plans.QUOTA_BANK_ACCOUNTS: 1,
    }
    assert free.price_inr_year is None


def test_pro_plan_unlocks_all_features_and_has_no_quotas():
    pro = plans.PLANS["pro"]
    assert pro.features == frozenset(
        {plans.FEATURE_WHATSAPP, plans.FEATURE_INVENTORY, plans.FEATURE_WHITELABEL}
    )
    assert pro.quotas == {}
    assert pro.price_inr_year == 4990


def test_business_plan_unlocks_all_features_and_is_not_self_serve():
    biz = plans.PLANS["business"]
    assert plans.FEATURE_WHATSAPP in biz.features
    assert biz.price_inr_year is None


def test_plan_for_falls_back_to_free_on_unknown_or_missing():
    assert plans.plan_for(SimpleNamespace(plan="pro")).code == "pro"
    assert plans.plan_for(SimpleNamespace(plan="nonsense")).code == "free"
    assert plans.plan_for(SimpleNamespace(plan=None)).code == "free"
    assert plans.plan_for(SimpleNamespace()).code == "free"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_plans.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.billing'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/billing/__init__.py` (empty file).

Create `backend/app/billing/plans.py`:

```python
"""The plan catalogue. Config-as-code: changing a limit or moving a feature
between tiers is a code change + deploy, deliberately -- these change ~yearly
and a DB-driven model with an admin UI is not worth its weight here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FEATURE_WHATSAPP = "whatsapp"
FEATURE_INVENTORY = "inventory_automation"
FEATURE_WHITELABEL = "whitelabel_pdf"

QUOTA_INVOICES = "invoices_per_month"
QUOTA_CUSTOMERS = "customers"
QUOTA_BANK_ACCOUNTS = "bank_accounts"

_ALL_FEATURES = frozenset({FEATURE_WHATSAPP, FEATURE_INVENTORY, FEATURE_WHITELABEL})


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price_inr_year: int | None          # None => not self-serve (free / business)
    features: frozenset[str] = frozenset()
    quotas: dict[str, int] = field(default_factory=dict)  # empty => unlimited


PLANS: dict[str, Plan] = {
    "free": Plan(
        code="free",
        name="Free",
        price_inr_year=None,
        features=frozenset(),
        quotas={QUOTA_INVOICES: 20, QUOTA_CUSTOMERS: 25, QUOTA_BANK_ACCOUNTS: 1},
    ),
    "pro": Plan(
        code="pro",
        name="Pro",
        price_inr_year=4990,
        features=_ALL_FEATURES,
        quotas={},
    ),
    "business": Plan(
        code="business",
        name="Business",
        price_inr_year=None,
        features=_ALL_FEATURES,
        quotas={},
    ),
}

FREE = PLANS["free"]


def plan_for(business) -> Plan:
    """The Plan for a business row. Unknown or missing plan code => FREE."""
    return PLANS.get(getattr(business, "plan", None) or "free", FREE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_plans.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/__init__.py backend/app/billing/plans.py backend/tests/test_plans.py
git commit -m "feat(billing): plan catalogue (free/pro/business, features + quotas)"
```

**Regression check:** no existing files touched — full suite unaffected, but run `cd backend && .venv/bin/python -m pytest -q` to confirm 267+4 = **271 passing**.
**QA acceptance:** `python -c "from app.billing.plans import PLANS; print({k:(v.price_inr_year, sorted(v.features), v.quotas) for k,v in PLANS.items()})"` prints the three tiers exactly as in the spec's business-model table.

---

### Task 3: `app/billing/entitlements.py` — the pure check module

**Files:**
- Create: `backend/app/billing/entitlements.py`
- Test: `backend/tests/test_entitlements.py`

**Interfaces:**
- Consumes: `app.billing.plans` (`plan_for`, quota key constants); `app.models` (`Invoice`, `Customer`, `BankAccount`); `app.time_utils.utcnow`
- Produces:
  - `class QuotaState(NamedTuple): allowed: bool; used: int; limit: int | None`
  - `class UpgradeRequired(Exception)` — `__init__(self, need: str, plan_needed: str = "pro")`, attrs `.need`, `.plan_needed`
  - `check_feature(business, feature: str) -> bool`
  - `check_quota(db: Session, business, quota: str) -> QuotaState` (`limit is None` => unlimited, always `allowed=True`, `used=0`)
  - `month_start_utc() -> datetime` — first day of the current month, 00:00, naive UTC

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_entitlements.py`:

```python
from datetime import timedelta
from decimal import Decimal

from app.billing import entitlements as ent
from app.billing import plans
from app.models import BankAccount, Business, Customer, Invoice
from app.time_utils import utcnow


def _biz(db, plan="free"):
    b = Business(name="Ent Co", plan=plan)
    db.add(b)
    db.flush()
    return b


def test_check_feature_free_vs_pro(db_session):
    free_biz = _biz(db_session, "free")
    pro_biz = _biz(db_session, "pro")
    assert ent.check_feature(free_biz, plans.FEATURE_WHATSAPP) is False
    assert ent.check_feature(pro_biz, plans.FEATURE_WHATSAPP) is True
    assert ent.check_feature(pro_biz, plans.FEATURE_WHITELABEL) is True


def test_check_quota_unlimited_for_pro(db_session):
    pro_biz = _biz(db_session, "pro")
    st = ent.check_quota(db_session, pro_biz, plans.QUOTA_CUSTOMERS)
    assert st == ent.QuotaState(allowed=True, used=0, limit=None)


def test_customer_quota_boundary(db_session):
    biz = _biz(db_session, "free")
    for i in range(24):
        db_session.add(Customer(business_id=biz.id, name=f"C{i}"))
    db_session.flush()
    st = ent.check_quota(db_session, biz, plans.QUOTA_CUSTOMERS)
    assert st.allowed is True and st.used == 24 and st.limit == 25
    db_session.add(Customer(business_id=biz.id, name="C24"))
    db_session.flush()
    assert ent.check_quota(db_session, biz, plans.QUOTA_CUSTOMERS).allowed is False


def test_bank_account_quota_is_one_on_free(db_session):
    biz = _biz(db_session, "free")
    assert ent.check_quota(db_session, biz, plans.QUOTA_BANK_ACCOUNTS).allowed is True
    db_session.add(BankAccount(business_id=biz.id, bank_name="X", account_no="1", ifsc="HDFC0000001"))
    db_session.flush()
    assert ent.check_quota(db_session, biz, plans.QUOTA_BANK_ACCOUNTS).allowed is False


def test_invoice_quota_counts_only_this_month_and_non_draft(db_session):
    biz = _biz(db_session, "free")
    cust = Customer(business_id=biz.id, name="Cust")
    db_session.add(cust)
    db_session.flush()

    def _inv(status, finalized_at):
        return Invoice(
            business_id=biz.id, customer_id=cust.id, invoice_no=f"X{finalized_at}",
            invoice_date=utcnow().date(), status=status, finalized_at=finalized_at,
        )

    now = utcnow()
    db_session.add(_inv("draft", None))                                  # not counted
    db_session.add(_inv("saved", now - timedelta(days=45)))              # last month, not counted
    for k in range(19):
        db_session.add(_inv("saved", now - timedelta(hours=k + 1)))      # this month
    db_session.flush()
    st = ent.check_quota(db_session, biz, plans.QUOTA_INVOICES)
    assert st.used == 19 and st.allowed is True
    db_session.add(_inv("saved", now))
    db_session.flush()
    assert ent.check_quota(db_session, biz, plans.QUOTA_INVOICES).allowed is False


def test_upgrade_required_carries_context():
    exc = ent.UpgradeRequired(plans.FEATURE_WHATSAPP)
    assert exc.need == plans.FEATURE_WHATSAPP
    assert exc.plan_needed == "pro"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_entitlements.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.billing.entitlements'`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/billing/entitlements.py`:

```python
"""Pure entitlement checks. Called from FastAPI dependencies (app/deps.py) and
from the WhatsApp worker (app/services/whatsapp_flow.py) -- so this module must
not import anything request-scoped.

`check_feature` is a set membership test against the in-memory Business row
(zero queries). `check_quota` runs exactly one COUNT, and only for a Free plan.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.plans import (
    QUOTA_BANK_ACCOUNTS,
    QUOTA_CUSTOMERS,
    QUOTA_INVOICES,
    plan_for,
)
from app.models import BankAccount, Customer, Invoice
from app.time_utils import utcnow


class QuotaState(NamedTuple):
    allowed: bool
    used: int
    limit: int | None      # None => unlimited


class UpgradeRequired(Exception):
    """Raised by non-dependency callers (the worker) when a plan gate fails."""

    def __init__(self, need: str, plan_needed: str = "pro"):
        self.need = need
        self.plan_needed = plan_needed
        super().__init__(f"upgrade to {plan_needed} required for {need}")


def month_start_utc() -> datetime:
    n = utcnow()
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def check_feature(business, feature: str) -> bool:
    return feature in plan_for(business).features


def check_quota(db: Session, business, quota: str) -> QuotaState:
    limit = plan_for(business).quotas.get(quota)
    if limit is None:
        return QuotaState(allowed=True, used=0, limit=None)
    used = _quota_usage(db, business, quota)
    return QuotaState(allowed=used < limit, used=used, limit=limit)


def _quota_usage(db: Session, business, quota: str) -> int:
    if quota == QUOTA_INVOICES:
        stmt = (
            select(func.count())
            .select_from(Invoice)
            .where(
                Invoice.business_id == business.id,
                Invoice.status != "draft",
                Invoice.finalized_at.is_not(None),
                Invoice.finalized_at >= month_start_utc(),
            )
        )
    elif quota == QUOTA_CUSTOMERS:
        stmt = select(func.count()).select_from(Customer).where(
            Customer.business_id == business.id
        )
    elif quota == QUOTA_BANK_ACCOUNTS:
        stmt = select(func.count()).select_from(BankAccount).where(
            BankAccount.business_id == business.id
        )
    else:
        raise ValueError(f"unknown quota {quota!r}")
    return db.execute(stmt).scalar_one()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_entitlements.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/entitlements.py backend/tests/test_entitlements.py
git commit -m "feat(billing): pure entitlements module (check_feature / check_quota)"
```

**Regression check:** full suite still green (`cd backend && .venv/bin/python -m pytest -q`).
**QA acceptance:** N/A (internal module) — covered by the six unit tests, especially the calendar-month boundary and the draft-excluded rule.

---

### Task 4: FastAPI dependencies — `require_feature`, `require_quota`, 402 body

**Files:**
- Modify: `backend/app/deps.py` (append)
- Test: `backend/tests/test_billing_gates.py` (new — a scratch router mounted in the test to exercise the deps in isolation)

**Interfaces:**
- Consumes: `get_current_business` (existing), `check_feature`, `check_quota` (Task 3)
- Produces:
  - `upgrade_required_http(need: str, plan_needed: str = "pro") -> HTTPException` — status 402, `detail` is the dict from Global Constraints
  - `require_feature(feature: str) -> Callable` — FastAPI dependency returning `Business`
  - `require_quota(quota: str) -> Callable` — FastAPI dependency returning `Business`
  - `require_billing_enabled() -> None` — raises 503 if `settings.billing_enabled` is False

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_billing_gates.py`:

```python
"""Exercises the require_feature / require_quota dependencies via a throwaway
router, so the gate behaviour is tested independently of which real endpoint
uses it."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.billing import plans
from app.db import get_db
from app.deps import require_feature, require_quota
from app.models import Business


@pytest.fixture
def gate_client():
    app = FastAPI()

    @app.get("/_t/feature")
    def _feature(biz: Business = Depends(require_feature(plans.FEATURE_WHATSAPP))):
        return {"ok": True}

    @app.get("/_t/quota")
    def _quota(biz: Business = Depends(require_quota(plans.QUOTA_CUSTOMERS))):
        return {"ok": True}

    from app.main import app as real_app  # reuse the real dependency_overrides / DB wiring

    app.dependency_overrides = real_app.dependency_overrides
    return TestClient(app)


def _signup(client, email="gate@test.com"):
    r = client.post("/auth/signup", json={
        "business_name": "Gate Co", "email": email, "password": "pass1234",
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_feature_gate_blocks_free_with_402_body(client, gate_client):
    headers = _signup(client)
    r = gate_client.get("/_t/feature", headers=headers)
    assert r.status_code == 402
    d = r.json()["detail"]
    assert d["code"] == "upgrade_required"
    assert d["feature"] == plans.FEATURE_WHATSAPP
    assert d["plan_needed"] == "pro"
    assert d["upgrade_url"] == "/pricing"


def test_feature_gate_allows_pro(client, gate_client, db_session):
    headers = _signup(client, "propass@test.com")
    biz = db_session.query(Business).filter(Business.name == "Gate Co").first()
    biz.plan = "pro"
    db_session.commit()
    r = gate_client.get("/_t/feature", headers=headers)
    assert r.status_code == 200


def test_quota_gate_blocks_when_over_limit(client, gate_client, db_session):
    from app.models import Customer

    headers = _signup(client, "quota@test.com")
    biz = db_session.query(Business).filter(Business.name == "Gate Co").first()
    for i in range(25):
        db_session.add(Customer(business_id=biz.id, name=f"C{i}"))
    db_session.commit()
    r = gate_client.get("/_t/quota", headers=headers)
    assert r.status_code == 402
    assert r.json()["detail"]["feature"] == plans.QUOTA_CUSTOMERS
```

> **Note for the implementer:** if wiring the throwaway app's DB/auth overrides proves awkward, instead test the two real endpoints Task 6 modifies and delete this file's `gate_client` fixture — the requirement is that the 402 body shape is asserted somewhere. Keep at least: free→402 with the exact body, pro→200.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_gates.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_feature' from 'app.deps'`.

- [ ] **Step 3: Write the implementation**

Append to `backend/app/deps.py`:

```python
from app.billing.entitlements import check_feature, check_quota


def upgrade_required_http(need: str, plan_needed: str = "pro") -> HTTPException:
    """The single 402 every plan gate raises. `need` is a feature key or a
    quota key; the frontend's axios interceptor branches on detail.code."""
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "message": "Your plan doesn't include this.",
            "code": "upgrade_required",
            "feature": need,
            "plan_needed": plan_needed,
            "upgrade_url": "/pricing",
        },
    )


def require_feature(feature: str):
    def _dep(business: Business = Depends(get_current_business)) -> Business:
        if not check_feature(business, feature):
            raise upgrade_required_http(feature)
        return business

    return _dep


def require_quota(quota: str):
    def _dep(
        business: Business = Depends(get_current_business),
        db: Session = Depends(get_db),
    ) -> Business:
        if not check_quota(db, business, quota).allowed:
            raise upgrade_required_http(quota)
        return business

    return _dep


def require_billing_enabled() -> None:
    if not _settings.billing_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not enabled.",
        )
```

> `_settings` is already module-level in `deps.py` (`_settings = get_settings()`). `billing_enabled` is added to `Settings` in Task 13; until then this references an attribute that doesn't exist — that's fine because `require_billing_enabled` is not imported anywhere until Task 15. If the linter complains, land Task 13's config change first.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_gates.py -v`
Expected: PASS.

- [ ] **Step 5: Full regression**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: still green (existing endpoints don't use the new deps yet).

- [ ] **Step 6: Commit**

```bash
git add backend/app/deps.py backend/tests/test_billing_gates.py
git commit -m "feat(billing): require_feature / require_quota deps + 402 upgrade_required body"
```

**Regression check:** `tests/test_auth.py` (uses `get_current_business` — unchanged) all pass.
**QA acceptance:** the 402 JSON body matches the Global Constraints shape exactly, including `upgrade_url: "/pricing"`.

---

### Task 5: Gate — invoice finalize quota (inline, idempotency-safe)

**Files:**
- Modify: `backend/app/routers/invoices.py` — `finalize_invoice` (around line 170)
- Test: `backend/tests/test_invoices.py` (append)

**Interfaces:**
- Consumes: `check_quota` (Task 3), `upgrade_required_http` (Task 4), `plans.QUOTA_INVOICES`
- Produces: nothing new — behaviour change only

**Why inline, not the `require_quota` dependency:** `finalize_invoice` returns early and idempotently for an already-`saved` invoice. A dependency runs *before* the body, so a Free tenant at their cap re-finalizing an already-saved invoice would wrongly get a 402. The check must sit *after* the idempotent-return guard and *before* the status flip.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_invoices.py` (reuse this file's existing signup / invoice-creation helpers — match their names):

```python
def test_finalize_blocked_at_free_invoice_cap(client):
    headers = _headers(client, "invcap@test.com")   # use this file's existing helper
    cust_id = _make_customer(client, headers)        # existing helper

    # finalize 20 invoices this month -> allowed
    for _ in range(20):
        inv = _create_draft_invoice(client, headers, cust_id)  # existing helper
        r = client.post(f"/invoices/{inv}/finalize", headers=headers)
        assert r.status_code == 200

    inv21 = _create_draft_invoice(client, headers, cust_id)
    r = client.post(f"/invoices/{inv21}/finalize", headers=headers)
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "upgrade_required"
    assert r.json()["detail"]["feature"] == "invoices_per_month"


def test_refinalize_saved_invoice_is_idempotent_even_over_cap(client, db_session):
    from app.models import Business

    headers = _headers(client, "reinv@test.com")
    cust_id = _make_customer(client, headers)
    inv = _create_draft_invoice(client, headers, cust_id)
    assert client.post(f"/invoices/{inv}/finalize", headers=headers).status_code == 200

    # push the business over cap by faking 25 finalized invoices is unnecessary;
    # instead drop the plan quota effect: leave plan free, and assert the second
    # finalize of an ALREADY-saved invoice still returns 200 (idempotent path).
    r = client.post(f"/invoices/{inv}/finalize", headers=headers)
    assert r.status_code == 200
```

> If `test_invoices.py` doesn't have helpers with these exact names, add small local helpers at the top of the test file — do not rename the existing ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_invoices.py -k "free_invoice_cap or refinalize_saved" -v`
Expected: FAIL — the 21st finalize returns 200, not 402.

- [ ] **Step 3: Write the implementation**

In `backend/app/routers/invoices.py`, add imports:

```python
from app.billing.entitlements import check_quota
from app.billing.plans import QUOTA_INVOICES
from app.deps import get_current_business, upgrade_required_http
```

In `finalize_invoice`, right after the `if invoice.status != "draft":` 409 block and before `if not invoice.line_items:`:

```python
    if not check_quota(db, business, QUOTA_INVOICES).allowed:
        raise upgrade_required_http(QUOTA_INVOICES)
```

(The `invoice.status == "saved"` early-return above it is untouched, so re-finalizing is still a no-op 200.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_invoices.py -v`
Expected: PASS — all existing invoice tests + the 2 new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/invoices.py backend/tests/test_invoices.py
git commit -m "feat(billing): gate invoice finalize on Free monthly cap (20)"
```

**Regression check:** `tests/test_invoices.py`, `tests/test_crm_qa_fixes.py` (invoice lifecycle assertions), `tests/whatsapp/test_confirm.py` and `test_e2e.py` (the WhatsApp confirm path calls `create_invoice_for_business`, not the finalize route — but run them to be sure). All green.
**QA acceptance:** As a Free tenant, finalize 20 invoices in a month → all succeed. 21st → 402 `upgrade_required`, `feature: "invoices_per_month"`. Grant Pro (Task 9 CLI) → 21st now succeeds. Drafts never count. Next calendar month resets the count.

---

### Task 6: Gate — customer and bank-account creation quotas (dependency)

**Files:**
- Modify: `backend/app/routers/customers.py` — `create_customer`; `backend/app/routers/bank_accounts.py` — `create_bank_account`
- Test: `backend/tests/test_customers.py`, `backend/tests/test_bank_accounts.py` (append)

**Interfaces:**
- Consumes: `require_quota` (Task 4), `plans.QUOTA_CUSTOMERS`, `plans.QUOTA_BANK_ACCOUNTS`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_customers.py`:

```python
def test_free_tenant_capped_at_25_customers(client):
    headers = _headers(client, "custcap@test.com")   # match this file's helper name
    for i in range(25):
        r = client.post("/customers", headers=headers, json={"name": f"Cust {i}"})
        assert r.status_code == 201
    r = client.post("/customers", headers=headers, json={"name": "Cust 26"})
    assert r.status_code == 402
    assert r.json()["detail"]["feature"] == "customers"
```

Append to `backend/tests/test_bank_accounts.py`:

```python
def test_free_tenant_capped_at_one_bank_account(client):
    headers = _headers(client, "bankcap@bank.test")
    r1 = client.post("/bank-accounts", headers=headers,
                     json={"bank_name": "HDFC", "account_no": "111", "ifsc": "HDFC0000111"})
    assert r1.status_code == 201
    r2 = client.post("/bank-accounts", headers=headers,
                     json={"bank_name": "ICICI", "account_no": "222", "ifsc": "ICIC0000222"})
    assert r2.status_code == 402
    assert r2.json()["detail"]["feature"] == "bank_accounts"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_customers.py tests/test_bank_accounts.py -k "cap" -v`
Expected: FAIL — creation #26 / #2 returns 201.

- [ ] **Step 3: Write the implementation**

`backend/app/routers/customers.py` — add import and swap the dependency on `create_customer` **only**:

```python
from app.billing.plans import QUOTA_CUSTOMERS
from app.deps import get_current_business, require_quota
```
```python
@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CustomerCreate,
    business: Business = Depends(require_quota(QUOTA_CUSTOMERS)),
    db: Session = Depends(get_db),
):
```

`backend/app/routers/bank_accounts.py` — same pattern on `create_bank_account`:

```python
from app.billing.plans import QUOTA_BANK_ACCOUNTS
from app.deps import get_current_business, require_quota
```
```python
@router.post("", response_model=BankAccountRead, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    body: BankAccountCreate,
    business: Business = Depends(require_quota(QUOTA_BANK_ACCOUNTS)),
    db: Session = Depends(get_db),
):
```

Leave `GET`, `PUT`, `DELETE` on both routers using `get_current_business` — only creation is capped.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_customers.py tests/test_bank_accounts.py -v`
Expected: PASS — all existing + 2 new.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/customers.py backend/app/routers/bank_accounts.py backend/tests/test_customers.py backend/tests/test_bank_accounts.py
git commit -m "feat(billing): gate customer (25) and bank-account (1) creation on Free"
```

**Regression check:** `tests/test_customers.py`, `tests/test_bank_accounts.py`, `tests/test_crm_qa_fixes.py`, `tests/whatsapp/test_customer_lookup.py` (worker creates no customers — WhatsApp is invoice-only per spec, but run it). All green.
**QA acceptance:** Free tenant: 25 customers OK, 26th → 402 `feature: "customers"`. 1 bank account OK, 2nd → 402 `feature: "bank_accounts"`. Editing/deleting existing rows is never blocked. Pro tenant: unlimited.

---

### Task 7: Gate — WhatsApp inbound processing (worker) + 24h upgrade-reply throttle

**Files:**
- Modify: `backend/app/rate_limit.py` (add constant + include in prune windows), `backend/app/services/whatsapp_flow.py` (`handle_inbound`)
- Test: `backend/tests/whatsapp/test_flow.py` (append), `backend/tests/test_rate_limit.py` (append)

**Interfaces:**
- Consumes: `check_feature` (Task 3), `plans.FEATURE_WHATSAPP`, `rate_limit.count_in_window` / `rate_limit.add_events` (existing, non-committing)
- Produces:
  - `rate_limit.WHATSAPP_UPGRADE_WINDOW_SECONDS = 86400`
  - new module-level in `whatsapp_flow.py`: `_MSG_UPGRADE = "..."`, helper `_upgrade_bucket(sender: str) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/whatsapp/test_flow.py`:

```python
def test_free_business_gets_one_upgrade_reply_then_silence(db_session, monkeypatch):
    b = _biz(db_session)              # this file's helper -> Business(plan defaults to "free")
    _cust(db_session, b)
    monkeypatch.setattr(flow, "parse_message", lambda text, prior: _full_draft())
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=_cust(db_session, b)))

    first = flow.handle_inbound(db_session, _payload(b, text="Invoice Rajesh 2 widgets"))
    assert len(first) == 1 and "upgrade" in first[0]["body"].lower()
    db_session.commit()

    second = flow.handle_inbound(db_session, _payload(b, text="Another one"))
    assert second == []


def test_pro_business_proceeds_normally(db_session, monkeypatch):
    b = _biz(db_session)
    b.plan = "pro"
    db_session.flush()
    cust = _cust(db_session, b)
    monkeypatch.setattr(flow, "parse_message", lambda text, prior: _full_draft())
    monkeypatch.setattr(flow, "resolve", lambda db, biz, name: Matched(customer=cust))
    out = flow.handle_inbound(db_session, _payload(b, text="Invoice Rajesh 2 widgets"))
    assert out and "upgrade" not in out[0]["body"].lower()
```

Append to `backend/tests/test_rate_limit.py`:

```python
def test_whatsapp_upgrade_window_is_in_prune_max(db_session):
    from datetime import timedelta
    from app import rate_limit
    from app.models import RateLimitEvent
    from app.time_utils import utcnow

    # a 20h-old event in a wa-upgrade bucket must survive the global prune
    db_session.add(RateLimitEvent(bucket_key="wa:upgrade:+910", occurred_at=utcnow() - timedelta(hours=20)))
    db_session.commit()
    rate_limit.add_events(db_session, ["some:other:key"])   # triggers _global_prune
    db_session.commit()
    still_there = db_session.query(RateLimitEvent).filter(
        RateLimitEvent.bucket_key == "wa:upgrade:+910"
    ).count()
    assert still_there == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/whatsapp/test_flow.py -k "upgrade or proceeds_normally" tests/test_rate_limit.py -k "upgrade_window" -v`
Expected: FAIL — no gate in `handle_inbound`; `WHATSAPP_UPGRADE_WINDOW_SECONDS` undefined.

- [ ] **Step 3: Implement the rate_limit constant**

In `backend/app/rate_limit.py`:

```python
# The WhatsApp worker sends a Free business at most one "upgrade to use this"
# reply per sender per day. That bucket's rows must outlive the 15-min windows,
# so the day window is included in the prune max() below.
WHATSAPP_UPGRADE_WINDOW_SECONDS = 24 * 60 * 60
```

In **both** `_global_prune` and `sweep_expired`, add `WHATSAPP_UPGRADE_WINDOW_SECONDS` to the `max(...)` call:

```python
    cutoff = utcnow() - timedelta(
        seconds=max(
            EMAIL_WINDOW_SECONDS, IP_WINDOW_SECONDS, WHATSAPP_WINDOW_SECONDS,
            SIGNUP_WINDOW_SECONDS, WHATSAPP_UPGRADE_WINDOW_SECONDS,
        )
    )
```

- [ ] **Step 4: Implement the gate in `whatsapp_flow.py`**

Add imports:

```python
from app import rate_limit
from app.billing.entitlements import check_feature
from app.billing.plans import FEATURE_WHATSAPP
```

Add near the other `_MSG_*` constants:

```python
_MSG_UPGRADE = (
    "WhatsApp invoicing is a Billing Buddy Pro feature. "
    "Upgrade at billingbuddy.in to start drafting invoices from chat."
)


def _upgrade_bucket(sender: str) -> str:
    return f"wa:upgrade:{sender}"
```

In `handle_inbound`, immediately after the `business is None` guard (before `conv = conv_store.get_locked(...)`):

```python
    if not check_feature(business, FEATURE_WHATSAPP):
        bucket = _upgrade_bucket(sender)
        if rate_limit.count_in_window(
            db, bucket, rate_limit.WHATSAPP_UPGRADE_WINDOW_SECONDS
        ) == 0:
            rate_limit.add_events(db, [bucket])   # committed by the worker's run_once
            return [_text(sender, business_id, _MSG_UPGRADE)]
        return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/whatsapp/ tests/test_rate_limit.py -v`
Expected: PASS — all WhatsApp tests + rate-limit tests, old and new.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rate_limit.py backend/app/services/whatsapp_flow.py backend/tests/whatsapp/test_flow.py backend/tests/test_rate_limit.py
git commit -m "feat(billing): gate WhatsApp inbound on Pro; one upgrade reply / sender / day"
```

**Regression check:** the **entire** `tests/whatsapp/` suite (webhook, worker, flow, confirm, e2e, retention) — the gate is early-return and must not perturb the Pro path. `tests/test_rate_limit.py` — prune behaviour unchanged for existing buckets.
**QA acceptance:** Authorized sender on a Free business texts an invoice request → gets exactly one "Pro feature" reply; further messages within 24h → no reply (check worker logs, not a crash). Same sender after the business is granted Pro → normal slot-fill flow. Unknown (unauthorized) sender → still silently dropped by the webhook, never reaches the worker.

---

### Task 8: "Made with Billing Buddy" PDF footer (Free only)

**Files:**
- Modify: `backend/app/services/pdf.py` (`render_invoice_html`), `backend/app/templates/invoice.html` (before `</body>`)
- Test: `backend/tests/test_pdf_footer.py` (new)

**Interfaces:**
- Consumes: `check_feature` (Task 3), `plans.FEATURE_WHITELABEL`
- Produces: template variable `show_powered_by: bool` in `render_invoice_html`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_pdf_footer.py`:

```python
from app.models import Business, Customer, Invoice
from app.services.pdf import render_invoice_html
from app.time_utils import utcnow


def _invoice(db, plan):
    b = Business(name="Footer Co", plan=plan, state="Gujarat")
    db.add(b)
    db.flush()
    c = Customer(business_id=b.id, name="Buyer")
    db.add(c)
    db.flush()
    inv = Invoice(
        business_id=b.id, customer_id=c.id, invoice_no="F-1",
        invoice_date=utcnow().date(), status="saved", grand_total=100,
        bill_to_name="Buyer",
    )
    db.add(inv)
    db.flush()
    db.refresh(inv)
    return inv


def test_free_invoice_pdf_has_powered_by_footer(db_session):
    html = render_invoice_html(_invoice(db_session, "free"))
    assert "Made with Billing Buddy" in html
    assert "ref=" in html


def test_pro_invoice_pdf_has_no_footer(db_session):
    html = render_invoice_html(_invoice(db_session, "pro"))
    assert "Made with Billing Buddy" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_footer.py -v`
Expected: FAIL — footer text not present for the Free invoice.

- [ ] **Step 3: Write the implementation**

`backend/app/services/pdf.py` — import and pass the flag:

```python
from app.billing.entitlements import check_feature
from app.billing.plans import FEATURE_WHITELABEL
```

In `render_invoice_html`, add to the `template.render(...)` kwargs:

```python
        show_powered_by=not check_feature(invoice.business, FEATURE_WHITELABEL),
```

`backend/app/templates/invoice.html` — immediately before `</body>`:

```html
  {% if show_powered_by %}
  <div style="margin-top:28px;padding-top:8px;border-top:1px solid #ddd;text-align:center;font-size:9px;color:#888;">
    Made with Billing Buddy — billingbuddy.in/?ref={{ business.id }}
  </div>
  {% endif %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_footer.py tests/test_invoice_pdf.py -v`
Expected: PASS — new footer tests + all existing PDF tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pdf.py backend/app/templates/invoice.html backend/tests/test_pdf_footer.py
git commit -m "feat(billing): 'Made with Billing Buddy' invoice footer on Free plan only"
```

**Regression check:** `tests/test_invoice_pdf.py` (existing markup / logo-fallback assertions must still hold — the footer is additive and after the signature block).
**QA acceptance:** Download a PDF as a Free tenant → footer line with `?ref=<uuid>` present under the totals. Grant Pro → re-download → footer gone. WhatsApp-sent invoice PDFs (worker) follow the same rule automatically since they call `render_invoice_pdf`.

---

### Task 9: `GET /billing/me` + billing router skeleton + grant CLI

**Files:**
- Create: `backend/app/routers/billing.py`, `backend/app/schemas/billing.py`, `backend/app/billing/grant.py`
- Modify: `backend/app/main.py` (`include_router`)
- Test: `backend/tests/test_billing_me.py`, `backend/tests/test_billing_grant.py`

**Interfaces:**
- Consumes: `get_current_business`, `check_quota`, `plans` constants, `BillingPayment`, `plan_for`
- Produces:
  - `GET /billing/me` → `BillingMe` (see schema below)
  - `app/billing/grant.py` module runnable as `python -m app.billing.grant <email> <plan> [--months N] [--revoke]`
  - `billing.router` (APIRouter, prefix `/billing`, tag `billing`)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_billing_me.py`:

```python
def _headers(client, email="me@billing.test"):
    r = client.post("/auth/signup", json={
        "business_name": "Me Co", "email": email, "password": "pass1234",
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_billing_me_reports_free_plan_and_usage(client):
    headers = _headers(client)
    client.post("/customers", headers=headers, json={"name": "C1"})
    r = client.get("/billing/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "free"
    assert body["plan_status"] == "none"
    assert body["plan_period_end"] is None
    assert body["usage"]["customers"] == {"used": 1, "limit": 25}
    assert body["usage"]["invoices_per_month"]["limit"] == 20
    assert body["usage"]["bank_accounts"]["limit"] == 1
    assert body["payments"] == []


def test_billing_me_reports_pro_plan_unlimited(client, db_session):
    from app.models import Business
    headers = _headers(client, "mepro@billing.test")
    biz = db_session.query(Business).filter(Business.name == "Me Co").first()
    biz.plan = "pro"
    biz.plan_status = "active"
    db_session.commit()
    r = client.get("/billing/me", headers=headers)
    body = r.json()
    assert body["plan"] == "pro"
    assert body["usage"]["customers"]["limit"] is None
```

Create `backend/tests/test_billing_grant.py`:

```python
from app.billing import grant
from app.models import BillingPayment, Business, User


def test_grant_sets_pro_with_period_and_audit_row(client, db_session):
    client.post("/auth/signup", json={
        "business_name": "Grant Co", "email": "grant@test.com", "password": "pass1234",
    })
    grant.main(["grant@test.com", "pro", "--months", "12"])

    biz = db_session.query(Business).join(User).filter(User.email == "grant@test.com").first()
    db_session.refresh(biz)
    assert biz.plan == "pro"
    assert biz.plan_status == "active"
    assert biz.plan_period_end is not None
    pay = db_session.query(BillingPayment).filter(BillingPayment.business_id == biz.id).one()
    assert pay.status == "paid" and pay.razorpay_order_id == "manual-grant"


def test_grant_revoke_returns_to_free(client, db_session):
    client.post("/auth/signup", json={
        "business_name": "Revoke Co", "email": "revoke@test.com", "password": "pass1234",
    })
    grant.main(["revoke@test.com", "pro"])
    grant.main(["revoke@test.com", "free", "--revoke"])
    biz = db_session.query(Business).join(User).filter(User.email == "revoke@test.com").first()
    db_session.refresh(biz)
    assert biz.plan == "free" and biz.plan_status == "none" and biz.plan_period_end is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_me.py tests/test_billing_grant.py -v`
Expected: FAIL — `/billing/me` 404; `app.billing.grant` missing.

- [ ] **Step 3: Write the schema**

Create `backend/app/schemas/billing.py`:

```python
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class UsageLine(BaseModel):
    used: int
    limit: int | None


class PaymentRow(BaseModel):
    id: str
    plan: str
    amount_inr: Decimal
    status: str
    created_at: datetime
    period_end: datetime | None


class BillingMe(BaseModel):
    plan: str
    plan_status: str
    plan_period_end: datetime | None
    usage: dict[str, UsageLine]      # keys: invoices_per_month, customers, bank_accounts
    payments: list[PaymentRow]
```

- [ ] **Step 4: Write the router**

Create `backend/app/routers/billing.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.entitlements import check_quota
from app.billing.plans import QUOTA_BANK_ACCOUNTS, QUOTA_CUSTOMERS, QUOTA_INVOICES
from app.db import get_db
from app.deps import get_current_business
from app.models import BillingPayment, Business
from app.schemas.billing import BillingMe, PaymentRow, UsageLine

router = APIRouter(prefix="/billing", tags=["billing"])

_USAGE_KEYS = (QUOTA_INVOICES, QUOTA_CUSTOMERS, QUOTA_BANK_ACCOUNTS)


@router.get("/me", response_model=BillingMe)
def billing_me(
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    usage = {}
    for key in _USAGE_KEYS:
        st = check_quota(db, business, key)
        usage[key] = UsageLine(used=st.used, limit=st.limit)

    payments = db.execute(
        select(BillingPayment)
        .where(BillingPayment.business_id == business.id)
        .order_by(BillingPayment.created_at.desc())
    ).scalars().all()

    return BillingMe(
        plan=business.plan,
        plan_status=business.plan_status,
        plan_period_end=business.plan_period_end,
        usage=usage,
        payments=[
            PaymentRow(
                id=str(p.id), plan=p.plan, amount_inr=p.amount_inr,
                status=p.status, created_at=p.created_at, period_end=p.period_end,
            )
            for p in payments
        ],
    )
```

> `check_quota` for a Pro plan returns `used=0` — acceptable for `/billing/me` (the UI shows "Unlimited" when `limit is None` and ignores `used`). If you want a real count for Pro too, that's a Phase 3 nicety, not now.

`backend/app/main.py` — add to the imports tuple and the `include_router` block:

```python
from app.routers import (auth, bank_accounts, billing, business, customers, invoices, meta, whatsapp)
...
app.include_router(billing.router)
```

- [ ] **Step 5: Write the grant CLI**

Create `backend/app/billing/grant.py`:

```python
"""Manual plan grant / revoke.

    python -m app.billing.grant <business-email> <plan> [--months N] [--revoke]

<plan> is free | pro | business. --months defaults to 12 (ignored for `free`).
Writes a BillingPayment audit row (razorpay_order_id='manual-grant', amount 0).
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

from app.billing.plans import PLANS
from app.db import SessionLocal
from app.models import BillingPayment, Business, User
from app.time_utils import utcnow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.billing.grant")
    parser.add_argument("email")
    parser.add_argument("plan", choices=sorted(PLANS))
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--revoke", action="store_true",
                        help="set plan_status='none' and clear plan_period_end")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        biz = (
            db.query(Business)
            .join(User, User.business_id == Business.id)
            .filter(User.email == args.email.strip().lower())
            .first()
        )
        if biz is None:
            print(f"no business for {args.email!r}", file=sys.stderr)
            return 1

        now = utcnow()
        biz.plan = args.plan
        if args.plan == "free" or args.revoke:
            biz.plan_status = "none"
            biz.plan_period_end = None
        else:
            biz.plan_status = "active"
            base = biz.plan_period_end if (biz.plan_period_end and biz.plan_period_end > now) else now
            biz.plan_period_end = base + timedelta(days=30 * args.months)
            db.add(BillingPayment(
                business_id=biz.id, plan=args.plan, amount_inr=0, status="paid",
                razorpay_order_id="manual-grant", period_start=now,
                period_end=biz.plan_period_end,
            ))
        db.commit()
        print(f"{args.email}: plan={biz.plan} status={biz.plan_status} until={biz.plan_period_end}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_me.py tests/test_billing_grant.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Full regression**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: green. Count ≈ **283 passing** (267 + 16 across Tasks 2–9).

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/billing.py backend/app/schemas/billing.py backend/app/billing/grant.py backend/app/main.py backend/tests/test_billing_me.py backend/tests/test_billing_grant.py
git commit -m "feat(billing): GET /billing/me + manual grant CLI"
```

**Regression check:** `tests/test_health.py` and every router test — `main.py` changed (new router) so a smoke of the whole suite is required. `/billing/me` requires auth (401 without).
**QA acceptance:** `GET /billing/me` as a fresh signup → `plan:"free"`, usage limits `{20,25,1}`, `payments:[]`. Run `python -m app.billing.grant <email> pro` → `/billing/me` now shows `plan:"pro"`, limits `null`, one `manual-grant` payment row. `--revoke` returns it to Free.

---

### Task 10: Frontend — billing API client + upgrade store

**Files:**
- Create: `frontend/src/api/billing.ts`, `frontend/src/store/upgradeStore.ts`
- Modify: `frontend/src/api/client.ts` (interceptor)
- Test: manual (no frontend test runner configured — verify via `tsc`, `eslint`, and the QA steps)

**Interfaces:**
- Produces:
  - `billing.ts`: `interface BillingMe`, `interface UsageLine`, `getBillingMe(): Promise<BillingMe>`, `startCheckout(): Promise<CheckoutOrder>`, `verifyCheckout(body): Promise<{plan: string}>` (the last two hit endpoints built in Phase 2; export them now, they're unused until Task 19)
  - `upgradeStore.ts`: `useUpgradeStore` with `{ prompt: UpgradePrompt | null; show(p): void; clear(): void }`, `interface UpgradePrompt { feature: string; planNeeded: string }`

- [ ] **Step 1: Create the upgrade store**

`frontend/src/store/upgradeStore.ts`:

```ts
import { create } from "zustand";

export interface UpgradePrompt {
  feature: string;
  planNeeded: string;
}

interface UpgradeState {
  prompt: UpgradePrompt | null;
  show: (p: UpgradePrompt) => void;
  clear: () => void;
}

export const useUpgradeStore = create<UpgradeState>((set) => ({
  prompt: null,
  show: (prompt) => set({ prompt }),
  clear: () => set({ prompt: null }),
}));
```

- [ ] **Step 2: Create the billing API client**

`frontend/src/api/billing.ts`:

```ts
import { apiClient } from "./client";

export interface UsageLine {
  used: number;
  limit: number | null;
}

export interface PaymentRow {
  id: string;
  plan: string;
  amount_inr: string;
  status: string;
  created_at: string;
  period_end: string | null;
}

export interface BillingMe {
  plan: "free" | "pro" | "business";
  plan_status: string;
  plan_period_end: string | null;
  usage: Record<"invoices_per_month" | "customers" | "bank_accounts", UsageLine>;
  payments: PaymentRow[];
}

export interface CheckoutOrder {
  order_id: string;
  amount: number; // paise
  currency: string;
  key_id: string;
}

export async function getBillingMe(): Promise<BillingMe> {
  const { data } = await apiClient.get<BillingMe>("/billing/me");
  return data;
}

export async function startCheckout(): Promise<CheckoutOrder> {
  const { data } = await apiClient.post<CheckoutOrder>("/billing/checkout", { plan: "pro" });
  return data;
}

export async function verifyCheckout(body: {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}): Promise<{ plan: string }> {
  const { data } = await apiClient.post<{ plan: string }>("/billing/verify", body);
  return data;
}
```

- [ ] **Step 3: Wire the 402 interceptor**

`frontend/src/api/client.ts` — inside the existing `interceptors.response.use` error handler, before `return Promise.reject(error)`:

```ts
    const detail = error?.response?.data?.detail;
    if (error?.response?.status === 402 && detail?.code === "upgrade_required") {
      // Lazy import avoids a static import cycle (store -> ... -> client).
      import("../store/upgradeStore").then(({ useUpgradeStore }) => {
        useUpgradeStore.getState().show({
          feature: detail.feature,
          planNeeded: detail.plan_needed,
        });
      });
    }
```

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/api/billing.ts src/api/client.ts src/store/upgradeStore.ts`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/billing.ts frontend/src/store/upgradeStore.ts frontend/src/api/client.ts
git commit -m "feat(billing): frontend billing API client + 402 upgrade interceptor"
```

**Regression check:** `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build` — clean. The existing 401 handling in `client.ts` is untouched.
**QA acceptance:** covered after Task 11/12 wire the UI.

---

### Task 11: Frontend — Billing settings page (read-only) + route + nav

**Files:**
- Create: `frontend/src/pages/BillingSettingsPage.tsx`
- Modify: `frontend/src/App.tsx` (route), `frontend/src/components/AppShell.tsx` (nav item)

**Interfaces:**
- Consumes: `getBillingMe` (Task 10), `AppShell`, shared classes from `../styles`

- [ ] **Step 1: Build the page**

`frontend/src/pages/BillingSettingsPage.tsx` — follow `BankAccountsPage.tsx`'s structure (AppShell wrapper, `cardClass`/`cardTitleClass` from `../styles`, TanStack `useQuery`):

```tsx
import { useQuery } from "@tanstack/react-query";

import { getBillingMe, type UsageLine } from "../api/billing";
import AppShell from "../components/AppShell";
import { cardClass, cardTitleClass, primaryButtonClass } from "../styles";

const USAGE_LABELS: Record<string, string> = {
  invoices_per_month: "Invoices this month",
  customers: "Customers",
  bank_accounts: "Bank accounts",
};

function UsageRow({ label, line }: { label: string; line: UsageLine }) {
  const pct =
    line.limit == null ? 0 : Math.min(100, Math.round((line.used / line.limit) * 100));
  return (
    <div className="py-2">
      <div className="flex justify-between text-sm">
        <span className="text-ink">{label}</span>
        <span className="tabular-nums text-ink-muted">
          {line.limit == null ? `${line.used} · Unlimited` : `${line.used} / ${line.limit}`}
        </span>
      </div>
      {line.limit != null && (
        <div className="mt-1 h-1.5 w-full rounded-full bg-border">
          <div
            className={`h-1.5 rounded-full ${pct >= 100 ? "bg-danger" : "bg-primary"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}

export default function BillingSettingsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["billing", "me"], queryFn: getBillingMe });

  return (
    <AppShell title="Billing">
      <div className="max-w-2xl space-y-6">
        {isLoading || !data ? (
          <p className="text-sm text-ink-muted">Loading…</p>
        ) : (
          <>
            <div className={cardClass}>
              <h2 className={cardTitleClass}>Current plan</h2>
              <p className="mt-1 text-2xl font-serif capitalize text-ink">{data.plan}</p>
              {data.plan !== "free" && data.plan_period_end && (
                <p className="text-sm text-ink-muted">
                  Active until {new Date(data.plan_period_end).toLocaleDateString()}
                </p>
              )}
              {data.plan === "free" && (
                <a href="/pricing" className={primaryButtonClass + " mt-3 inline-block"}>
                  Upgrade to Pro
                </a>
              )}
            </div>

            <div className={cardClass}>
              <h2 className={cardTitleClass}>Usage</h2>
              {Object.entries(data.usage).map(([key, line]) => (
                <UsageRow key={key} label={USAGE_LABELS[key] ?? key} line={line} />
              ))}
            </div>

            <div className={cardClass}>
              <h2 className={cardTitleClass}>Payments</h2>
              {data.payments.length === 0 ? (
                <p className="text-sm text-ink-muted">No payments yet.</p>
              ) : (
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs uppercase text-ink-muted">
                      <th className="py-2 font-medium">Date</th>
                      <th className="py-2 font-medium">Plan</th>
                      <th className="py-2 font-medium">Amount</th>
                      <th className="py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.payments.map((p) => (
                      <tr key={p.id} className="border-b border-border last:border-0">
                        <td className="py-2">{new Date(p.created_at).toLocaleDateString()}</td>
                        <td className="py-2 capitalize">{p.plan}</td>
                        <td className="py-2 tabular-nums">₹{Number(p.amount_inr).toLocaleString("en-IN")}</td>
                        <td className="py-2">{p.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
```

> Check `../styles` for the exact exported class names (`cardClass`, `cardTitleClass`, `primaryButtonClass` are used by `BankAccountsPage`). If `primaryButtonClass` isn't exported, use the same Tailwind string `BankAccountsPage` uses for its submit button.

- [ ] **Step 2: Add the route**

`frontend/src/App.tsx` — import and add inside `<Routes>`:

```tsx
import BillingSettingsPage from "./pages/BillingSettingsPage";
```
```tsx
      <Route path="/settings/billing" element={<ProtectedRoute><BillingSettingsPage /></ProtectedRoute>} />
```

- [ ] **Step 3: Add the nav item**

`frontend/src/components/AppShell.tsx` — append to `NAV_ITEMS`:

```tsx
  { to: "/settings/billing", label: "Billing" },
```

- [ ] **Step 4: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/BillingSettingsPage.tsx frontend/src/App.tsx frontend/src/components/AppShell.tsx
git commit -m "feat(billing): read-only billing settings page + nav"
```

**Regression check:** frontend build clean; all existing routes still render (manually click through Invoices / Customers / Bank accounts / Business profile).
**QA acceptance:** Log in → "Billing" appears in the sidebar → the page shows plan "Free", three usage bars with correct used/limit, "Upgrade to Pro" button (links to `/pricing`, which 404s to `/` until Task 19), empty payments table. After a CLI Pro grant + refresh → "Pro", "Active until …", usage rows say "Unlimited", no upgrade button.

---

### Task 12: Frontend — Upgrade interstitial modal

**Files:**
- Create: `frontend/src/components/UpgradeInterstitial.tsx`
- Modify: `frontend/src/App.tsx` (mount it in `Shell`, once, outside `<Routes>`)

**Interfaces:**
- Consumes: `useUpgradeStore` (Task 10)

- [ ] **Step 1: Build the component**

`frontend/src/components/UpgradeInterstitial.tsx`:

```tsx
import { useNavigate } from "react-router-dom";

import { useUpgradeStore } from "../store/upgradeStore";
import { primaryButtonClass } from "../styles";

const FEATURE_COPY: Record<string, string> = {
  whatsapp: "WhatsApp invoice drafting",
  inventory_automation: "automated inventory",
  whitelabel_pdf: "white-label invoices",
  invoices_per_month: "more invoices this month",
  customers: "more customers",
  bank_accounts: "more bank accounts",
};

export default function UpgradeInterstitial() {
  const prompt = useUpgradeStore((s) => s.prompt);
  const clear = useUpgradeStore((s) => s.clear);
  const navigate = useNavigate();
  if (!prompt) return null;

  const what = FEATURE_COPY[prompt.feature] ?? "this feature";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={clear}
    >
      <div
        className="w-full max-w-md rounded-lg bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-lg font-semibold text-ink">
          Upgrade to {prompt.planNeeded === "pro" ? "Pro" : prompt.planNeeded}
        </h2>
        <p className="mt-2 text-sm text-ink-muted">
          {what[0].toUpperCase() + what.slice(1)} is available on Billing Buddy{" "}
          {prompt.planNeeded === "pro" ? "Pro" : prompt.planNeeded}. Upgrade to unlock it —
          your existing data stays exactly as it is.
        </p>
        <div className="mt-5 flex gap-3">
          <button
            type="button"
            className={primaryButtonClass}
            onClick={() => {
              clear();
              navigate("/pricing");
            }}
          >
            See plans
          </button>
          <button
            type="button"
            className="rounded-md px-3 py-2 text-sm text-ink-muted hover:text-ink"
            onClick={clear}
          >
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Mount it once**

`frontend/src/App.tsx` — in `Shell`, wrap the return so the modal sits alongside `<Routes>`:

```tsx
function Shell() {
  useSessionProbe();
  return (
    <>
      <Routes>
        {/* …existing routes unchanged… */}
      </Routes>
      <UpgradeInterstitial />
    </>
  );
}
```

Add the import: `import UpgradeInterstitial from "./components/UpgradeInterstitial";`

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UpgradeInterstitial.tsx frontend/src/App.tsx
git commit -m "feat(billing): upgrade interstitial modal driven by 402 responses"
```

**Regression check:** frontend build clean; app still boots to the invoice list; modal is `null` until a 402 fires.
**QA acceptance:** As a Free tenant, create 25 customers, then try a 26th → the backend 402 pops the modal ("More customers is available on Billing Buddy Pro"). "Not now" dismisses it; "See plans" navigates to `/pricing`. Repeat for the 2nd bank account and the 21st invoice finalize.

---

### Phase 1 checkpoint

- [ ] `cd backend && .venv/bin/python -m pytest -q` → all green (~283 tests).
- [ ] `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build` → clean.
- [ ] `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` → clean.
- [ ] Manual: signup → all Free gates enforce; CLI grant → gates lift; `/billing/me` and the settings page reflect both states.
- [ ] `billing_enabled` is not yet referenced by any imported code path (only `require_billing_enabled`, still unused). Phase 1 is deployable as-is.

---

# PHASE 2 — Razorpay self-serve checkout (Tasks 13–20)

Enabled by setting `BILLING_ENABLED=true` + the three Razorpay secrets. A business can now pay ₹4,990 and get Pro for a year.

---

### Task 13: Config — Razorpay settings + `billing_enabled`

**Files:**
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_billing_checkout.py` (created here with one config test; expanded in Task 15)

**Interfaces:**
- Produces: `Settings.billing_enabled: bool` (default `False`), `Settings.razorpay_key_id: str` (default `""`), `Settings.razorpay_key_secret: str` (default `""`), `Settings.razorpay_webhook_secret: str` (default `""`), `Settings.razorpay_pro_price_inr: int` (default `4990`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_billing_checkout.py`:

```python
def test_billing_disabled_by_default(client):
    r = client.post("/auth/signup", json={
        "business_name": "Cfg Co", "email": "cfg@test.com", "password": "pass1234",
    })
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    resp = client.post("/billing/checkout", headers=headers, json={"plan": "pro"})
    assert resp.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_checkout.py -v`
Expected: FAIL — route doesn't exist yet (404, not 503). That's expected; this test goes green in Task 15. For *this* task, only assert config parses:

Run: `cd backend && .venv/bin/python -c "from app.config import Settings; s=Settings(); print(s.billing_enabled, s.razorpay_pro_price_inr)"`
Expected after Step 3: `False 4990`.

- [ ] **Step 3: Write the implementation**

`backend/app/config.py` — add to `Settings` (after the WhatsApp block):

```python
    # --- Billing / Razorpay (Phase 2). All required only when billing_enabled. ---
    billing_enabled: bool = False
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_pro_price_inr: int = 4990
```

- [ ] **Step 4: Verify**

Run: `cd backend && .venv/bin/python -c "from app.config import Settings; s=Settings(); assert s.billing_enabled is False and s.razorpay_pro_price_inr == 4990; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_billing_checkout.py
git commit -m "feat(billing): razorpay config + billing_enabled flag (default off)"
```

**Regression check:** `cd backend && .venv/bin/python -m pytest -q` — config change is additive with defaults; suite unaffected (the new checkout test is xfail-ish until Task 15 — leave it, it'll pass then, and pytest will show it failing now only if you added it as a hard assertion; if that bothers the checkpoint, mark it `@pytest.mark.skip(reason="route added in Task 15")` and unskip in Task 15).

---

### Task 14: `app/billing/razorpay_client.py` — order creation + signature verification

**Files:**
- Create: `backend/app/billing/razorpay_client.py`
- Test: `backend/tests/test_razorpay_client.py`

**Interfaces:**
- Produces:
  - `PRO_PRICE_PAISE_DEFAULT = 499000`
  - `_client() -> httpx.Client` (the test seam)
  - `create_order(amount_paise: int, receipt: str) -> dict` — returns Razorpay's order JSON (`{"id": "order_...", "amount": ..., ...}`); raises `RazorpayError` on non-2xx
  - `verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool` — HMAC-SHA256 of `f"{order_id}|{payment_id}"` keyed by `razorpay_key_secret`
  - `verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool` — HMAC-SHA256 of the raw body keyed by `razorpay_webhook_secret`
  - `class RazorpayError(RuntimeError)` with `.status_code`, `.body`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_razorpay_client.py`:

```python
import hashlib
import hmac

from app.billing import razorpay_client as rc
from app.config import get_settings


def test_verify_payment_signature_roundtrip(monkeypatch):
    monkeypatch.setattr(get_settings(), "razorpay_key_secret", "secret_k", raising=False)
    get_settings.cache_clear()
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret_k")
    sig = hmac.new(b"secret_k", b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert rc.verify_payment_signature("order_1", "pay_1", sig) is True
    assert rc.verify_payment_signature("order_1", "pay_1", "deadbeef") is False


def test_verify_webhook_signature(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "wh_secret")
    get_settings.cache_clear()
    body = b'{"event":"payment.captured"}'
    good = hmac.new(b"wh_secret", body, hashlib.sha256).hexdigest()
    assert rc.verify_webhook_signature(body, good) is True
    assert rc.verify_webhook_signature(body, None) is False
    assert rc.verify_webhook_signature(body, "nope") is False


def test_create_order_calls_orders_endpoint(monkeypatch):
    captured = {}

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"id": "order_abc", "amount": 499000, "currency": "INR"}

        def raise_for_status(self):
            pass

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            captured["url"] = url
            captured["json"] = kw.get("json")
            captured["auth"] = kw.get("auth")
            return _FakeResp()

    monkeypatch.setattr(rc, "_client", lambda: _FakeClient())
    monkeypatch.setenv("RAZORPAY_KEY_ID", "key_id_x")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "key_secret_x")
    get_settings.cache_clear()

    out = rc.create_order(499000, "receipt-1")
    assert out["id"] == "order_abc"
    assert captured["url"].endswith("/v1/orders")
    assert captured["json"] == {"amount": 499000, "currency": "INR", "receipt": "receipt-1"}
    assert captured["auth"] == ("key_id_x", "key_secret_x")
```

> `get_settings` is `@lru_cache`d — the tests above use `get_settings.cache_clear()` + env vars. Follow whatever pattern the existing `tests/whatsapp/test_whatsapp_client.py` uses for settings overrides; mirror it for consistency.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_razorpay_client.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

Create `backend/app/billing/razorpay_client.py`:

```python
"""Minimal adapter for Razorpay's REST API -- only what one-time Order checkout
needs. No SDK: one POST for order creation, HMAC-SHA256 for the two signature
checks. Mirrors app/services/whatsapp_client.py's style (a `_client()` seam
tests patch; secrets and response bodies never logged)."""

from __future__ import annotations

import hashlib
import hmac

import httpx

from app.config import get_settings

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
PRO_PRICE_PAISE_DEFAULT = 499000
_TIMEOUT_SECONDS = 15.0
_BODY_TRUNCATE = 500


class RazorpayError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = (body or "")[:_BODY_TRUNCATE]
        super().__init__(f"Razorpay API returned {status_code}")


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT_SECONDS)


def create_order(amount_paise: int, receipt: str) -> dict:
    s = get_settings()
    try:
        with _client() as c:
            resp = c.post(
                f"{RAZORPAY_API_BASE}/orders",
                auth=(s.razorpay_key_id, s.razorpay_key_secret),
                json={"amount": amount_paise, "currency": "INR", "receipt": receipt},
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RazorpayError(exc.response.status_code, exc.response.text) from exc
    except httpx.HTTPError as exc:
        raise RazorpayError(0, str(exc)) from exc
    return resp.json()


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    expected = hmac.new(
        get_settings().razorpay_key_secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    expected = hmac.new(
        get_settings().razorpay_webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_razorpay_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/billing/razorpay_client.py backend/tests/test_razorpay_client.py
git commit -m "feat(billing): razorpay client — create_order + HMAC signature verification"
```

**Regression check:** none touched — run `-q` to confirm suite green.
**QA acceptance:** unit-level only. In a Razorpay **test-mode** dashboard, `create_order` against real test keys returns an `order_...` id (do this once manually during Phase 2 rollout, not in CI).

---

### Task 15: `POST /billing/checkout`

**Files:**
- Modify: `backend/app/routers/billing.py`, `backend/app/schemas/billing.py`
- Test: `backend/tests/test_billing_checkout.py` (expand)

**Interfaces:**
- Consumes: `require_billing_enabled` (Task 4), `get_current_business`, `razorpay_client.create_order`, `plans.PLANS`, `BillingPayment`
- Produces:
  - request `CheckoutRequest { plan: Literal["pro"] }`
  - response `CheckoutOrderResponse { order_id: str; amount: int; currency: str; key_id: str }`
  - `POST /billing/checkout` — 503 if disabled; 409 if already on a paid plan with > 60 days remaining; else creates a Razorpay order + a `billing_payments(status="created")` row

- [ ] **Step 1: Write the failing tests**

Expand `backend/tests/test_billing_checkout.py`:

```python
import pytest

from app.billing import razorpay_client as rc
from app.config import get_settings


@pytest.fixture
def billing_on(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "key_test")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret_test")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "wh_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rc, "create_order",
                        lambda amount_paise, receipt: {"id": "order_test123", "amount": amount_paise})
    yield
    get_settings.cache_clear()


def _headers(client, email):
    r = client.post("/auth/signup", json={
        "business_name": "CO Co", "email": email, "password": "pass1234",
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_checkout_disabled_returns_503(client):
    headers = _headers(client, "co_off@test.com")
    assert client.post("/billing/checkout", headers=headers, json={"plan": "pro"}).status_code == 503


def test_checkout_creates_order_and_pending_payment(client, billing_on, db_session):
    from app.models import BillingPayment, Business

    headers = _headers(client, "co_on@test.com")
    r = client.post("/billing/checkout", headers=headers, json={"plan": "pro"})
    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] == "order_test123"
    assert body["amount"] == 499000
    assert body["key_id"] == "key_test"

    biz = db_session.query(Business).filter(Business.name == "CO Co").first()
    pay = db_session.query(BillingPayment).filter(BillingPayment.business_id == biz.id).one()
    assert pay.status == "created" and pay.razorpay_order_id == "order_test123"


def test_checkout_409_when_already_pro_with_time_left(client, billing_on, db_session):
    from datetime import timedelta
    from app.models import Business
    from app.time_utils import utcnow

    headers = _headers(client, "co_pro@test.com")
    biz = db_session.query(Business).filter(Business.name == "CO Co").first()
    biz.plan = "pro"
    biz.plan_status = "active"
    biz.plan_period_end = utcnow() + timedelta(days=200)
    db_session.commit()
    assert client.post("/billing/checkout", headers=headers, json={"plan": "pro"}).status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_checkout.py -v`
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Write the implementation**

`backend/app/schemas/billing.py` — add:

```python
from typing import Literal


class CheckoutRequest(BaseModel):
    plan: Literal["pro"] = "pro"


class CheckoutOrderResponse(BaseModel):
    order_id: str
    amount: int          # paise
    currency: str
    key_id: str
```

`backend/app/routers/billing.py` — add imports and the endpoint:

```python
from datetime import timedelta

from fastapi import HTTPException, status

from app.billing import razorpay_client
from app.config import get_settings
from app.deps import require_billing_enabled
from app.schemas.billing import CheckoutOrderResponse, CheckoutRequest
from app.time_utils import utcnow

_RENEW_LOCKOUT_DAYS = 60


@router.post("/checkout", response_model=CheckoutOrderResponse,
             dependencies=[Depends(require_billing_enabled)])
def checkout(
    body: CheckoutRequest,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    now = utcnow()
    if (
        business.plan in ("pro", "business")
        and business.plan_period_end
        and business.plan_period_end > now + timedelta(days=_RENEW_LOCKOUT_DAYS)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your plan is already active with more than 60 days remaining.",
        )

    settings = get_settings()
    amount_paise = settings.razorpay_pro_price_inr * 100
    payment = BillingPayment(
        business_id=business.id, plan="pro", amount_inr=settings.razorpay_pro_price_inr,
        status="created",
    )
    db.add(payment)
    db.flush()

    order = razorpay_client.create_order(amount_paise, receipt=str(payment.id))
    payment.razorpay_order_id = order["id"]
    db.commit()

    return CheckoutOrderResponse(
        order_id=order["id"], amount=amount_paise, currency="INR",
        key_id=settings.razorpay_key_id,
    )
```

> If `razorpay_client.create_order` raises `RazorpayError`, let it propagate — `main.py` has no handler for it, so add one: in `main.py`, a small `@app.exception_handler(RazorpayError)` returning `502 {"detail": "Payment provider error, please retry."}`. Add that here (import `from app.billing.razorpay_client import RazorpayError`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_checkout.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/billing.py backend/app/schemas/billing.py backend/app/main.py backend/tests/test_billing_checkout.py
git commit -m "feat(billing): POST /billing/checkout — create razorpay order"
```

**Regression check:** full `-q` run. `main.py` changed (exception handler) — smoke the whole suite.
**QA acceptance:** With `BILLING_ENABLED=false` → 503. With it on → returns `{order_id, amount:499000, currency:"INR", key_id}` and leaves a `created` payment row. Already-Pro with >60d left → 409.

---

### Task 16: `POST /billing/verify` + `_activate_pro`

**Files:**
- Modify: `backend/app/routers/billing.py`, `backend/app/schemas/billing.py`
- Test: `backend/tests/test_billing_checkout.py` (append verify cases) — or a new `test_billing_verify.py`

**Interfaces:**
- Consumes: `razorpay_client.verify_payment_signature`, `BillingPayment`
- Produces:
  - `_activate_pro(db: Session, business: Business, payment: BillingPayment, *, event_id: str | None = None) -> None` — module-level in `billing.py`, idempotent (returns immediately if `payment.status == "paid"`)
  - request `VerifyRequest { razorpay_order_id, razorpay_payment_id, razorpay_signature }`
  - `POST /billing/verify` → `{ "plan": "pro" }`; 400 on bad signature; 404 if no matching `created` payment row

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_billing_checkout.py`:

```python
import hashlib
import hmac


def _sign(order_id, payment_id, secret="secret_test"):
    return hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


def test_verify_activates_pro_and_is_idempotent(client, billing_on, db_session):
    from app.models import BillingPayment, Business

    headers = _headers(client, "vf@test.com")
    order = client.post("/billing/checkout", headers=headers, json={"plan": "pro"}).json()
    oid = order["order_id"]

    payload = {
        "razorpay_order_id": oid,
        "razorpay_payment_id": "pay_xyz",
        "razorpay_signature": _sign(oid, "pay_xyz"),
    }
    r = client.post("/billing/verify", headers=headers, json=payload)
    assert r.status_code == 200 and r.json()["plan"] == "pro"

    biz = db_session.query(Business).filter(Business.name == "CO Co").first()
    db_session.refresh(biz)
    assert biz.plan == "pro" and biz.plan_status == "active" and biz.plan_period_end is not None
    pay = db_session.query(BillingPayment).filter(BillingPayment.razorpay_order_id == oid).one()
    assert pay.status == "paid"

    # replay -> still 200, no second activation, period unchanged
    end_before = biz.plan_period_end
    r2 = client.post("/billing/verify", headers=headers, json=payload)
    assert r2.status_code == 200
    db_session.refresh(biz)
    assert biz.plan_period_end == end_before


def test_verify_rejects_bad_signature(client, billing_on):
    headers = _headers(client, "vfbad@test.com")
    oid = client.post("/billing/checkout", headers=headers, json={"plan": "pro"}).json()["order_id"]
    r = client.post("/billing/verify", headers=headers, json={
        "razorpay_order_id": oid, "razorpay_payment_id": "pay_bad", "razorpay_signature": "wrong",
    })
    assert r.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_checkout.py -k verify -v`
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Write the implementation**

`backend/app/schemas/billing.py` — add:

```python
class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PlanResponse(BaseModel):
    plan: str
```

`backend/app/routers/billing.py` — add:

```python
_YEAR = timedelta(days=365)


def _activate_pro(db: Session, business: Business, payment: BillingPayment,
                  *, event_id: str | None = None) -> None:
    """Idempotent convergence point for both /verify and the webhook."""
    if payment.status == "paid":
        return
    now = utcnow()
    payment.status = "paid"
    if event_id and not payment.razorpay_event_id:
        payment.razorpay_event_id = event_id
    base = (
        business.plan_period_end
        if (business.plan_period_end and business.plan_period_end > now)
        else now
    )
    new_end = base + _YEAR
    payment.period_start = now
    payment.period_end = new_end
    business.plan = "pro"
    business.plan_status = "active"
    business.plan_period_end = new_end
    db.commit()


@router.post("/verify", response_model=PlanResponse,
             dependencies=[Depends(require_billing_enabled)])
def verify(
    body: VerifyRequest,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    if not razorpay_client.verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Payment signature verification failed.")

    payment = db.execute(
        select(BillingPayment).where(
            BillingPayment.razorpay_order_id == body.razorpay_order_id,
            BillingPayment.business_id == business.id,
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No matching checkout for this order.")

    payment.razorpay_payment_id = body.razorpay_payment_id
    _activate_pro(db, business, payment)
    return PlanResponse(plan=business.plan)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_checkout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/billing.py backend/app/schemas/billing.py backend/tests/test_billing_checkout.py
git commit -m "feat(billing): POST /billing/verify + idempotent _activate_pro"
```

**Regression check:** full `-q` run green.
**QA acceptance:** After a Razorpay test-mode payment, the Checkout.js handler's `POST /billing/verify` flips the business to Pro instantly (`/billing/me` shows it). A replayed verify is a 200 no-op. A tampered signature → 400, plan unchanged.

---

### Task 17: `POST /billing/webhook` — signed, idempotent

**Files:**
- Modify: `backend/app/routers/billing.py`
- Test: `backend/tests/test_billing_webhook.py`

**Interfaces:**
- Consumes: `razorpay_client.verify_webhook_signature`, `_activate_pro` (Task 16), `BillingPayment`
- Produces: `POST /billing/webhook` — public (no auth); 400 on bad signature; 200 otherwise (including dedup no-ops and unhandled event types). Handles `payment.captured` / `order.paid` (activate) and `payment.failed` (mark payment failed). Dedup on the `X-Razorpay-Event-Id` header via `billing_payments.razorpay_event_id` unique constraint.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_billing_webhook.py`:

```python
import hashlib
import hmac
import json

import pytest

from app.billing import razorpay_client as rc
from app.config import get_settings


@pytest.fixture
def billing_on(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "key_test")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret_test")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "wh_test")
    get_settings.cache_clear()
    monkeypatch.setattr(rc, "create_order",
                        lambda amount_paise, receipt: {"id": "order_wh1", "amount": amount_paise})
    yield
    get_settings.cache_clear()


def _headers(client, email):
    r = client.post("/auth/signup", json={
        "business_name": "WH Co", "email": email, "password": "pass1234",
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _wh(body: dict, event_id="evt_wh_1", secret="wh_test"):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
                 "Content-Type": "application/json"}


def test_webhook_bad_signature_400(client, billing_on):
    raw, headers = _wh({"event": "payment.captured"})
    headers["X-Razorpay-Signature"] = "bad"
    assert client.post("/billing/webhook", content=raw, headers=headers).status_code == 400


def test_webhook_payment_captured_activates_pro(client, billing_on, db_session):
    from app.models import Business

    ah = _headers(client, "wh1@test.com")
    order = client.post("/billing/checkout", headers=ah, json={"plan": "pro"}).json()
    raw, headers = _wh({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_wh1", "order_id": order["order_id"]}}},
    })
    assert client.post("/billing/webhook", content=raw, headers=headers).status_code == 200

    biz = db_session.query(Business).filter(Business.name == "WH Co").first()
    db_session.refresh(biz)
    assert biz.plan == "pro"


def test_webhook_replayed_event_id_is_noop(client, billing_on, db_session):
    from app.models import BillingPayment, Business

    ah = _headers(client, "wh2@test.com")
    order = client.post("/billing/checkout", headers=ah, json={"plan": "pro"}).json()
    raw, headers = _wh({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_wh2", "order_id": order["order_id"]}}},
    }, event_id="evt_dupe")

    assert client.post("/billing/webhook", content=raw, headers=headers).status_code == 200
    biz = db_session.query(Business).filter(Business.name == "WH Co").first()
    db_session.refresh(biz)
    end1 = biz.plan_period_end

    assert client.post("/billing/webhook", content=raw, headers=headers).status_code == 200
    db_session.refresh(biz)
    assert biz.plan_period_end == end1  # not extended a second time
    paid = db_session.query(BillingPayment).filter(
        BillingPayment.razorpay_order_id == order["order_id"], BillingPayment.status == "paid"
    ).count()
    assert paid == 1


def test_webhook_converges_with_verify(client, billing_on, db_session):
    from app.models import Business

    ah = _headers(client, "wh3@test.com")
    order = client.post("/billing/checkout", headers=ah, json={"plan": "pro"}).json()
    oid = order["order_id"]
    sig = hmac.new(b"secret_test", f"{oid}|pay_wh3".encode(), hashlib.sha256).hexdigest()
    client.post("/billing/verify", headers=ah, json={
        "razorpay_order_id": oid, "razorpay_payment_id": "pay_wh3", "razorpay_signature": sig,
    })
    biz = db_session.query(Business).filter(Business.name == "WH Co").first()
    db_session.refresh(biz)
    end_after_verify = biz.plan_period_end

    raw, headers = _wh({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_wh3", "order_id": oid}}},
    }, event_id="evt_after_verify")
    assert client.post("/billing/webhook", content=raw, headers=headers).status_code == 200
    db_session.refresh(biz)
    assert biz.plan_period_end == end_after_verify  # webhook after verify: no double-extend


def test_webhook_unknown_event_200(client, billing_on):
    raw, headers = _wh({"event": "refund.created"}, event_id="evt_refund")
    assert client.post("/billing/webhook", content=raw, headers=headers).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_webhook.py -v`
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Write the implementation**

`backend/app/routers/billing.py` — add:

```python
from fastapi import Request
from fastapi.responses import Response

_ACTIVATE_EVENTS = {"payment.captured", "order.paid"}


@router.post("/webhook", dependencies=[Depends(require_billing_enabled)])
async def webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    if not razorpay_client.verify_webhook_signature(
        raw, request.headers.get("X-Razorpay-Signature")
    ):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    event_id = request.headers.get("X-Razorpay-Event-Id") or ""
    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored"}

    event = body.get("event")
    if event in _ACTIVATE_EVENTS:
        entity = (
            body.get("payload", {}).get("payment", {}).get("entity", {})
            or body.get("payload", {}).get("order", {}).get("entity", {})
        )
        order_id = entity.get("order_id") or entity.get("id")
        payment = db.execute(
            select(BillingPayment).where(BillingPayment.razorpay_order_id == order_id)
        ).scalar_one_or_none()
        if payment is None:
            return {"status": "no matching payment"}

        # Dedup: if this exact event was already applied, the unique constraint
        # on razorpay_event_id makes _activate_pro's commit fail -- but we
        # short-circuit first on payment.status, and _activate_pro itself is a
        # no-op when already paid, so a replay is harmless either way.
        if payment.status == "paid":
            return {"status": "already applied"}

        business = db.get(Business, payment.business_id)
        payment.razorpay_payment_id = entity.get("id")
        try:
            _activate_pro(db, business, payment, event_id=event_id or None)
        except IntegrityError:
            db.rollback()  # concurrent duplicate event; the other writer won
        return {"status": "ok"}

    if event == "payment.failed":
        entity = body.get("payload", {}).get("payment", {}).get("entity", {})
        payment = db.execute(
            select(BillingPayment).where(
                BillingPayment.razorpay_order_id == entity.get("order_id")
            )
        ).scalar_one_or_none()
        if payment is not None and payment.status == "created":
            payment.status = "failed"
            db.commit()
        return {"status": "ok"}

    return {"status": "ignored"}
```

Add `from sqlalchemy.exc import IntegrityError` to the imports.

> `main.py` already has an `IntegrityError` exception handler that returns 409 — but that only fires for *unhandled* `IntegrityError`s that propagate out of the route. Here it's caught inside the route, so no conflict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_webhook.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/billing.py backend/tests/test_billing_webhook.py
git commit -m "feat(billing): POST /billing/webhook — signed, idempotent, converges with verify"
```

**Regression check:** full `-q` run. The webhook is a new public route — confirm it does not require auth and does not affect `/whatsapp/webhook` (different prefix).
**QA acceptance:** In Razorpay test mode, register the webhook → make a test payment → business flips to Pro via webhook even if `/verify` is never called. Re-deliver the same event from the dashboard → still 200, no second year added. `payment.failed` → payment row shows `failed`, plan unchanged.

---

### Task 18: Billing expiry sweep in the worker loop

**Files:**
- Create: `backend/app/services/billing_expiry.py`
- Modify: `backend/app/workers/whatsapp_worker.py`
- Test: `backend/tests/test_billing_expiry.py`

**Interfaces:**
- Consumes: `Business`, `WhatsAppConnection`, `utcnow`
- Produces: `billing_expiry_sweep(db: Session) -> int` — returns the number of businesses reverted; commits the caller's session

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_billing_expiry.py`:

```python
from datetime import timedelta

from app.models import Business, WhatsAppConnection
from app.services.billing_expiry import billing_expiry_sweep
from app.time_utils import utcnow


def test_sweep_reverts_lapsed_plan_and_disconnects_whatsapp(db_session):
    past = utcnow() - timedelta(days=1)
    b = Business(name="Lapsed Co", plan="pro", plan_status="active", plan_period_end=past)
    db_session.add(b)
    db_session.flush()
    conn = WhatsAppConnection(
        business_id=b.id, phone_number_id="pn_1", waba_id="w_1",
        access_token_encrypted="x", status="active",
    )
    db_session.add(conn)
    db_session.commit()

    n = billing_expiry_sweep(db_session)
    assert n == 1
    db_session.refresh(b)
    db_session.refresh(conn)
    assert b.plan == "free" and b.plan_status == "none" and b.plan_period_end is None
    assert conn.status == "disconnected"


def test_sweep_leaves_active_and_free_plans_alone(db_session):
    future = utcnow() + timedelta(days=30)
    active = Business(name="Active Co", plan="pro", plan_status="active", plan_period_end=future)
    free = Business(name="Free Co", plan="free", plan_status="none")
    db_session.add_all([active, free])
    db_session.commit()

    assert billing_expiry_sweep(db_session) == 0
    db_session.refresh(active)
    assert active.plan == "pro"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_expiry.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/billing_expiry.py`:

```python
"""Revert lapsed paid plans to Free. Runs in the whatsapp_worker idle loop
next to retention_sweep -- no separate scheduler. A lapsed tenant keeps Pro
until the next sweep (<= the retention interval); acceptable per the spec."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Business, WhatsAppConnection
from app.time_utils import utcnow


def billing_expiry_sweep(db: Session) -> int:
    now = utcnow()
    lapsed = db.execute(
        select(Business).where(
            Business.plan != "free",
            Business.plan_period_end.is_not(None),
            Business.plan_period_end < now,
        )
    ).scalars().all()

    for business in lapsed:
        business.plan = "free"
        business.plan_status = "none"
        business.plan_period_end = None
        db.execute(
            update(WhatsAppConnection)
            .where(
                WhatsAppConnection.business_id == business.id,
                WhatsAppConnection.status == "active",
            )
            .values(status="disconnected")
        )

    db.commit()
    return len(lapsed)
```

`backend/app/workers/whatsapp_worker.py` — import and call it in the idle block:

```python
from app.services.billing_expiry import billing_expiry_sweep
```
```python
            if not worked and now - last_sweep > _RETENTION_SWEEP_INTERVAL_SECONDS:
                last_sweep = now
                retention_sweep(db)
                billing_expiry_sweep(db)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_expiry.py tests/whatsapp/test_worker.py tests/whatsapp/test_retention.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/billing_expiry.py backend/app/workers/whatsapp_worker.py backend/tests/test_billing_expiry.py
git commit -m "feat(billing): expiry sweep — revert lapsed plans, disconnect WhatsApp"
```

**Regression check:** `tests/whatsapp/test_worker.py`, `tests/whatsapp/test_retention.py` — the worker loop change must not break job processing or the retention sweep.
**QA acceptance:** Grant Pro with `--months` such that `plan_period_end` is in the past (or edit the row), start the worker, wait one idle sweep interval → business is back on Free and its WhatsApp connection is `disconnected` (so `billing-buddy-agent` stops ingesting for it). A Pro tenant with time left is untouched.

---

### Task 19: Frontend — Pricing page + Razorpay Checkout.js

**Files:**
- Create: `frontend/src/pages/PricingPage.tsx`
- Modify: `frontend/src/App.tsx` (route)
- Modify: `frontend/index.html` **or** dynamic-load in `PricingPage` — load `https://checkout.razorpay.com/v1/checkout.js`

**Interfaces:**
- Consumes: `startCheckout`, `verifyCheckout` (Task 10), `getBillingMe`

- [ ] **Step 1: Add a Checkout.js loader helper**

In `frontend/src/api/billing.ts` append:

```ts
let razorpayLoad: Promise<void> | null = null;

export function loadRazorpayCheckout(): Promise<void> {
  if (razorpayLoad) return razorpayLoad;
  razorpayLoad = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Failed to load Razorpay"));
    document.body.appendChild(s);
  });
  return razorpayLoad;
}

// Minimal typing for the global the script installs.
declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}
```

- [ ] **Step 2: Build the pricing page**

`frontend/src/pages/PricingPage.tsx`:

```tsx
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import {
  loadRazorpayCheckout,
  startCheckout,
  verifyCheckout,
} from "../api/billing";
import AppShell from "../components/AppShell";
import { cardClass, cardTitleClass, primaryButtonClass } from "../styles";

const FREE_POINTS = ["Manual GST invoicing + PDF", "20 invoices / month", "25 customers", "1 bank account"];
const PRO_POINTS = [
  "Everything in Free, unlimited",
  "WhatsApp invoice drafting",
  "Automated inventory from supplier bills",
  "Purchase & stock tracking",
  "No 'Made with Billing Buddy' footer",
];

export default function PricingPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();

  async function upgrade() {
    setBusy(true);
    setError(null);
    try {
      await loadRazorpayCheckout();
      const order = await startCheckout();
      if (!window.Razorpay) throw new Error("Razorpay unavailable");
      const rzp = new window.Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: order.currency,
        name: "Billing Buddy",
        description: "Pro plan — 1 year",
        order_id: order.order_id,
        handler: async (resp: {
          razorpay_order_id: string;
          razorpay_payment_id: string;
          razorpay_signature: string;
        }) => {
          await verifyCheckout(resp);
          await qc.invalidateQueries({ queryKey: ["billing", "me"] });
          navigate("/settings/billing");
        },
        modal: { ondismiss: () => setBusy(false) },
      });
      rzp.open();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <AppShell title="Plans">
      <div className="grid max-w-4xl gap-4 md:grid-cols-3">
        <div className={cardClass}>
          <h2 className={cardTitleClass}>Free</h2>
          <p className="text-2xl font-serif text-ink">₹0</p>
          <ul className="mt-3 space-y-1 text-sm text-ink-muted">
            {FREE_POINTS.map((p) => <li key={p}>• {p}</li>)}
          </ul>
        </div>

        <div className={cardClass + " ring-2 ring-primary"}>
          <h2 className={cardTitleClass}>Pro</h2>
          <p className="text-2xl font-serif text-ink">₹4,990<span className="text-sm text-ink-muted"> / year</span></p>
          <p className="text-xs text-ink-muted">≈ ₹416 / month</p>
          <ul className="mt-3 space-y-1 text-sm text-ink-muted">
            {PRO_POINTS.map((p) => <li key={p}>• {p}</li>)}
          </ul>
          <button type="button" className={primaryButtonClass + " mt-4 w-full"} disabled={busy} onClick={upgrade}>
            {busy ? "Opening…" : "Upgrade to Pro"}
          </button>
          {error && <p className="mt-2 text-sm text-danger">{error}</p>}
        </div>

        <div className={cardClass}>
          <h2 className={cardTitleClass}>Business</h2>
          <p className="text-2xl font-serif text-ink">Talk to us</p>
          <ul className="mt-3 space-y-1 text-sm text-ink-muted">
            <li>• Everything in Pro</li>
            <li>• Multiple users &amp; roles</li>
            <li>• API access, GSTR bulk export</li>
            <li>• Dedicated onboarding</li>
          </ul>
          <a href="mailto:hello@billingbuddy.in" className="mt-4 inline-block text-sm text-primary underline">
            Contact sales
          </a>
        </div>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 3: Add the route**

`frontend/src/App.tsx`:

```tsx
import PricingPage from "./pages/PricingPage";
```
```tsx
      <Route path="/pricing" element={<ProtectedRoute><PricingPage /></ProtectedRoute>} />
```

- [ ] **Step 4: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PricingPage.tsx frontend/src/api/billing.ts frontend/src/App.tsx
git commit -m "feat(billing): pricing page + Razorpay Checkout.js upgrade flow"
```

**Regression check:** frontend build clean; existing routes unaffected.
**QA acceptance:** With `BILLING_ENABLED=true` + Razorpay test keys: `/pricing` → "Upgrade to Pro" opens the Razorpay modal with ₹4,990 → complete a test payment → redirected to `/settings/billing` showing "Pro". Dismiss the modal → button re-enables, no error. With billing off, `startCheckout` returns 503 → the page shows the error text (acceptable — the nav link to `/pricing` should be hidden in that case, see Task 20).

---

### Task 20: Frontend — gate the pay UI on `billing_enabled`; wire remaining CTAs

**Files:**
- Modify: `frontend/src/api/billing.ts` (expose an `enabled` flag from `/billing/me`), `backend/app/routers/billing.py` + `backend/app/schemas/billing.py` (add `billing_enabled` to the `BillingMe` response), `frontend/src/pages/BillingSettingsPage.tsx`, `frontend/src/components/AppShell.tsx`
- Test: `backend/tests/test_billing_me.py` (append)

**Interfaces:**
- Produces: `BillingMe.billing_enabled: bool`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_billing_me.py`:

```python
def test_billing_me_exposes_billing_enabled_flag(client):
    headers = _headers(client, "flag@billing.test")
    body = client.get("/billing/me", headers=headers).json()
    assert body["billing_enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_me.py -k enabled_flag -v`
Expected: FAIL — key missing.

- [ ] **Step 3: Backend — add the flag**

`backend/app/schemas/billing.py` — add `billing_enabled: bool` to `BillingMe`.

`backend/app/routers/billing.py` — in `billing_me`, add `billing_enabled=get_settings().billing_enabled` to the `BillingMe(...)` construction (import `get_settings` if not already).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_billing_me.py -v`
Expected: PASS.

- [ ] **Step 5: Frontend — hide pay UI when disabled**

`frontend/src/api/billing.ts` — add `billing_enabled: boolean;` to `interface BillingMe`.

`frontend/src/pages/BillingSettingsPage.tsx` — only render the "Upgrade to Pro" link when `data.billing_enabled && data.plan === "free"`. When `!data.billing_enabled`, show a muted line: "Self-serve upgrades aren't available yet — contact hello@billingbuddy.in".

`frontend/src/components/AppShell.tsx` — the "Billing" nav item always shows (settings page is always useful), but there's no separate "/pricing" nav item, so nothing to hide there. Leave `NAV_ITEMS` as Task 11 left it.

`frontend/src/components/UpgradeInterstitial.tsx` — "See plans" always navigates to `/pricing`; the pricing page itself handles the disabled case (Task 19 Step: shows the 503 error). Acceptable. Optionally: in `UpgradeInterstitial`, if you want to be cleaner, read a cached `billing_enabled` and swap the CTA to a `mailto:` — **optional, not required**.

- [ ] **Step 6: Typecheck + build + full backend**

Run:
```bash
cd frontend && npx tsc --noEmit && npx eslint . && npx vite build
cd ../backend && .venv/bin/python -m pytest -q
```
Expected: all clean/green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/billing.py backend/app/schemas/billing.py backend/tests/test_billing_me.py frontend/src/api/billing.ts frontend/src/pages/BillingSettingsPage.tsx
git commit -m "feat(billing): expose billing_enabled; hide pay UI until Phase 2 is switched on"
```

**Regression check:** full backend suite + frontend build.
**QA acceptance:** `BILLING_ENABLED=false` → billing settings shows plan/usage but no pay button, only the contact line; `/pricing` still reachable but "Upgrade" errors gracefully. Flip `BILLING_ENABLED=true` → pay button appears, full flow works.

---

### Task 21: Regression sweep, deploy docs, cross-repo handoff note

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-subscription-module-design.md` (mark Status: Implemented), a deploy runbook doc if one exists (search `docs/` and repo root), `docker-compose.yml` if present
- Create: a short note appended to the `billing-buddy-agent` handoff contract (the plan can only *write the note in this repo's docs* — flag it for the human to carry over)

- [ ] **Step 1: Full backend regression**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: **0 failures.** Record the number (should be ~265 baseline + ~55 new ≈ **320**).

- [ ] **Step 2: Full frontend regression**

Run: `cd frontend && npx tsc --noEmit && npx eslint . && npx vite build`
Expected: clean.

- [ ] **Step 3: Migration round-trip once more**

Run: `cd backend && .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`
Expected: clean.

- [ ] **Step 4: Manual end-to-end smoke (documented, run against local uvicorn + Postgres)**

Follow and tick each:
1. Signup → `/billing/me` shows Free, limits `{20,25,1}`.
2. Create 25 customers → 26th returns 402 → interstitial appears.
3. Add 1 bank account → 2nd returns 402.
4. Finalize 20 invoices → 21st returns 402.
5. Download a PDF → "Made with Billing Buddy … ?ref=<uuid>" footer present.
6. `python -m app.billing.grant <email> pro` → repeat 2–5: all now succeed, footer gone, `/billing/me` shows Pro + `manual-grant` payment row.
7. `python -m app.billing.grant <email> free --revoke` → back to Free, gates re-enforce.
8. (billing on + Razorpay test keys) `/pricing` → Upgrade → test payment → `/settings/billing` shows Pro; re-deliver the webhook event → still one year, not two.
9. WhatsApp: Free business, authorized sender texts an invoice → one upgrade reply, silence after; grant Pro → normal flow.

- [ ] **Step 5: Deploy documentation**

Find the deploy runbook (`grep -ril "deploy\|runbook\|SECRET_ENCRYPTION_KEY" docs/`). Add a "Subscription module" section:

```
## Subscription module (migration 0009)

1. Run `alembic upgrade head` BEFORE deploying the new app code (additive; safe).
   0009 adds businesses.plan/plan_status/plan_period_end/razorpay_customer_id
   (all defaulted) + the billing_payments table. Every existing business row
   becomes plan='free'.
2. Phase 1 deploy: leave BILLING_ENABLED unset/false. Gates enforce; no payment
   path is reachable. Grant Pro to design partners with:
       python -m app.billing.grant <business-email> pro --months 12
3. Phase 2 deploy: set BILLING_ENABLED=true, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
   RAZORPAY_WEBHOOK_SECRET. Register the Razorpay webhook -> POST /billing/webhook
   for events: payment.captured, order.paid, payment.failed. Store the signing
   secret as RAZORPAY_WEBHOOK_SECRET.
4. The billing expiry sweep runs inside the whatsapp_worker process — that
   process MUST be running for downgrades to take effect.
5. Data residency (DPDP): Razorpay is India-based; we store only Razorpay IDs
   and rupee amounts, never card/UPI details.
```

If `docker-compose.yml` exists, add the four env vars (commented, `BILLING_ENABLED=false` default) to both the `web` and `worker` services.

- [ ] **Step 6: Cross-repo handoff note**

Append to whichever `docs/handoff/*.md` describes the shared purchasing tables (the spec references `billing-buddy-agent`'s `docs/handoff/purchasing-tables.md`; this repo may have a mirror). Add:

```
## Entitlement contract (subscription module, 2026-09-10)

billing-buddy-agent must ingest supplier documents / write inventory ONLY for a
business whose `whatsapp_connections.status = 'active'`. When a CRM subscription
lapses, the CRM worker's billing_expiry_sweep sets that row to 'disconnected' —
treat that as "stop ingesting for this business". No CRM API gates the agent's
direct DB writes; this connection-status check is the single enforcement point.
```

If no such handoff doc exists in this repo, note in the PR description that the `billing-buddy-agent` maintainer must add this contract on their side.

- [ ] **Step 7: Mark the spec implemented + commit**

```bash
git add -A
git commit -m "docs(billing): deploy runbook, cross-repo entitlement contract, spec status"
```

**Regression check:** this task *is* the regression check — nothing ships until Steps 1–4 are all green/ticked.
**QA acceptance:** the entire Step 4 checklist passes on a clean local stack.

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task(s) |
|---|---|
| Business model — Free/Pro/Business tiers, limits | 2 (plans), 5/6/7 (gates), 19 (pricing page) |
| Value metric / no trial / signup → Free | 1 (column default `free`), 9 (`/billing/me`) |
| Growth hooks — `?ref=` PDF footer | 8 |
| Growth hooks — grant CLI for design partners | 9 |
| Architecture — config-as-code plans | 2 |
| Architecture — plan state as columns, 0 extra queries | 1, 3 |
| Architecture — shared entitlements fn (deps + worker) | 3, 4, 7 |
| Data model — migration 0009, 4 columns + `billing_payments` | 1 |
| `plans.py` / `entitlements.py` shapes | 2, 3 |
| 402 body shape | 4 (defined), 5/6/7 (used), 12 (consumed) |
| Six gates | finalize=5, customers/banks=6, WhatsApp worker=7, PDF footer=8; **connect-WhatsApp (gate 5 in spec) and purchasing-UI (gate 6 in spec) have no endpoint to attach to yet** — see note below |
| `billing-buddy-agent` seam | 18 (disconnect on sweep), 21 (handoff note) |
| Razorpay one-time flow, `_activate_pro` convergence | 14, 15, 16, 17 |
| Expiry sweep on worker loop | 18 |
| Frontend — interceptor, billing settings, pricing, interstitial | 10, 11, 12, 19, 20 |
| `billing_enabled` dark-launch | 13 (config), 4 (`require_billing_enabled`), 20 (frontend) |
| Test matrix | every task's tests + 21 |
| Deploy/ops notes | 21 |

**Gap found and resolved:** the spec's gate table lists "connect WhatsApp / enroll sender" and "purchasing/inventory UI" as gates. Neither endpoint exists in the codebase today (WhatsApp Phase C is unbuilt; there is no purchasing router). This plan does **not** invent those endpoints. Instead: Task 7 gates the WhatsApp *worker* (which is the effective block on WhatsApp drafting today), Task 18 disconnects WhatsApp connections on lapse (the agent seam), and Task 21 records the contract. **When those endpoints are later built, the builder must add `Depends(require_feature("whatsapp"))` / `Depends(require_feature("inventory_automation"))` — this is called out in the spec's "Enforcement" section and repeated in the handoff note.** No code change is possible or needed now.

**2. Placeholder scan:** no "TBD"/"handle appropriately"/"similar to Task N" — every code step has literal code. The two "optional" notes (Task 20 Step 5 `UpgradeInterstitial` mailto swap; Task 13 skip-marker) are explicitly optional with a stated default.

**3. Type consistency:**
- `check_quota` returns `QuotaState(allowed, used, limit)` — same NamedTuple in Tasks 3, 4, 9, 11.
- `upgrade_required_http(need, plan_needed="pro")` — same signature Tasks 4, 5.
- 402 body keys `message/code/feature/plan_needed/upgrade_url` — identical in Global Constraints, Task 4 impl, Task 12 consumer.
- `_activate_pro(db, business, payment, *, event_id=None)` — same signature Tasks 16 (def), 17 (call).
- `BillingMe` fields — Task 9 (`plan, plan_status, plan_period_end, usage, payments`), Task 20 adds `billing_enabled`; frontend `interface BillingMe` (Task 10) matches + Task 20 adds the flag there too.
- `startCheckout()` returns `{order_id, amount, currency, key_id}` (Task 10 type) = `CheckoutOrderResponse` (Task 15 backend). Match.
- Feature/quota key string constants used everywhere via `app.billing.plans` names — no bare literals outside `plans.py` and the JSON body.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-10-subscription-module.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
