import re
import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Business, Product, StockMovement, Supplier
from app.schemas.inventory import ProductCreate, SupplierCreate


class DuplicateNameError(Exception):
    """Raised when a product/supplier name normalizes to one that already
    exists for this business. Router translates to HTTP 409."""

    def __init__(self, entity: str):
        self.entity = entity
        super().__init__(f"a {entity} with this name already exists")

# trailing legal-entity suffixes, as token tuples, longest first
# Ported verbatim from billing-buddy-agent's src/bba/ingestion/matching.py
# (normalize_name) so manually-created products/suppliers dedupe against
# ones the WhatsApp ingestion pipeline creates. Keep in sync with that file.
_LEGAL_SUFFIXES: list[tuple[str, ...]] = [
    ("private", "limited"),
    ("pvt", "ltd"),
    ("and", "co"),
    ("&", "co"),
    ("limited",),
    ("ltd",),
    ("llp",),
    ("inc",),
    ("corporation",),
    ("corp",),
    ("co",),
]

_PUNCT_TO_SPACE = re.compile(r"[.,;:()\[\]]+")
_WS = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = _PUNCT_TO_SPACE.sub(" ", raw.lower())
    s = _WS.sub(" ", s).strip()
    tokens = s.split()
    while tokens and not any(c.isalnum() for c in tokens[0]):
        tokens.pop(0)
    while tokens and not any(c.isalnum() for c in tokens[-1]):
        tokens.pop()
    changed = True
    while changed and tokens:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            n = len(suffix)
            if len(tokens) > n and tuple(tokens[-n:]) == suffix:
                tokens = tokens[:-n]
                changed = True
                break
    return " ".join(tokens)


def apply_stock_movement(
    db: Session,
    product: Product,
    delta_qty: Decimal,
    reason: str,
    ref_type: str | None = None,
    ref_id: uuid.UUID | None = None,
    note: str | None = None,
) -> StockMovement:
    """The only path that may change product.current_qty.

    Inserts a stock_movements row and derives the new balance from it, rather
    than a bare UPDATE -- the agent's ingestion pipeline follows the same
    invariant (see billing-buddy-agent persist.py) and stock_movements.balance_after
    is a snapshot column other readers assume is always populated.
    """
    balance_after = product.current_qty + delta_qty
    movement = StockMovement(
        business_id=product.business_id,
        product_id=product.id,
        delta_qty=delta_qty,
        balance_after=balance_after,
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    db.add(movement)
    product.current_qty = balance_after
    db.flush()
    return movement


def create_product(db: Session, business: Business, body: ProductCreate) -> Product:
    name_norm = normalize_name(body.name)
    existing = (
        db.query(Product)
        .filter(Product.business_id == business.id, Product.name_norm == name_norm)
        .first()
    )
    if existing is not None:
        raise DuplicateNameError("product")

    product = Product(
        business_id=business.id,
        name=body.name,
        name_norm=name_norm,
        hsn_sac=body.hsn_sac,
        uom=body.uom,
        reorder_level=body.reorder_level,
        default_purchase_price=body.default_purchase_price,
        auto_created=False,
        needs_review=False,
    )
    try:
        with db.begin_nested():
            db.add(product)
            db.flush()
    except IntegrityError:
        # TOCTOU guard against the pre-check above -- see auth.py signup for
        # the same pattern against the live unique index. A SAVEPOINT (not a
        # plain rollback) so this only undoes this insert, not any other
        # work already flushed in the caller's transaction.
        raise DuplicateNameError("product") from None
    return product


def get_or_create_product(
    db: Session,
    business: Business,
    name: str,
    hsn_sac: str | None = None,
    uom: str | None = None,
    default_purchase_price: Decimal | None = None,
) -> Product:
    """Look up a product by name_norm, or create it (manual origin: both
    auto_created and needs_review false, same as an explicit create_product
    call). Used by manual purchase entry when a line item names a product by
    free text rather than an existing product_id."""
    name_norm = normalize_name(name)
    existing = (
        db.query(Product)
        .filter(Product.business_id == business.id, Product.name_norm == name_norm)
        .first()
    )
    if existing is not None:
        return existing

    product = Product(
        business_id=business.id,
        name=name,
        name_norm=name_norm,
        hsn_sac=hsn_sac,
        uom=uom,
        default_purchase_price=default_purchase_price,
        auto_created=False,
        needs_review=False,
    )
    try:
        with db.begin_nested():
            db.add(product)
            db.flush()
    except IntegrityError:
        # Concurrent create raced us to the same name_norm -- fetch it.
        return (
            db.query(Product)
            .filter(Product.business_id == business.id, Product.name_norm == name_norm)
            .one()
        )
    return product


def create_supplier(db: Session, business: Business, body: SupplierCreate) -> Supplier:
    name_norm = normalize_name(body.name)
    existing = (
        db.query(Supplier)
        .filter(Supplier.business_id == business.id, Supplier.name_norm == name_norm)
        .first()
    )
    if existing is not None:
        raise DuplicateNameError("supplier")

    supplier = Supplier(
        business_id=business.id,
        name=body.name,
        name_norm=name_norm,
        gstin=body.gstin,
        phone=body.phone,
        email=body.email,
        address=body.address,
        state_code=body.state_code,
    )
    try:
        with db.begin_nested():
            db.add(supplier)
            db.flush()
    except IntegrityError:
        raise DuplicateNameError("supplier") from None
    return supplier
