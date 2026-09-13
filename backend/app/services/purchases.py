import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Business, Product, Purchase, PurchaseLineItem, Supplier
from app.schemas.purchase import PurchaseCreate
from app.services.inventory import apply_stock_movement, get_or_create_product

TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class SupplierNotFoundError(Exception):
    """Raised when a purchase references a supplier that doesn't exist or
    doesn't belong to the business. Router -> HTTP 404."""


class ProductNotFoundError(Exception):
    """Raised when a purchase line item references a product_id that
    doesn't exist or doesn't belong to the business. Router -> HTTP 404."""


class DuplicatePurchaseError(Exception):
    """Raised when (business_id, supplier_id, invoice_no) already exists.
    Router -> HTTP 409."""


def _resolve_supplier(db: Session, business: Business, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.business_id != business.id:
        raise SupplierNotFoundError("Supplier not found")
    return supplier


def _resolve_line_product(db: Session, business: Business, li) -> Product:
    if li.product_id is not None:
        product = db.get(Product, li.product_id)
        if product is None or product.business_id != business.id:
            raise ProductNotFoundError("Product not found")
        return product
    return get_or_create_product(
        db, business, li.product_name, hsn_sac=li.hsn_sac, uom=li.uom, default_purchase_price=li.price
    )


def create_purchase_for_business(db: Session, business: Business, body: PurchaseCreate) -> Purchase:
    """Build and persist (flush, not commit) a manually-entered purchase.

    Does not commit -- the caller (router) owns the transaction boundary.
    Resolves/creates every line item's product before touching the purchases
    table, so a duplicate-invoice_no conflict on the final flush rolls back
    the whole purchase atomically, including any product it would have
    auto-created.
    """
    supplier = _resolve_supplier(db, business, body.supplier_id)
    resolved = [
        (li, _resolve_line_product(db, business, li)) for li in body.line_items
    ]

    line_taxables = [_q(li.qty * li.price - li.discount) for li, _ in resolved]
    line_taxes = [
        _q(taxable * li.gst_rate / Decimal("100"))
        for (li, _), taxable in zip(resolved, line_taxables)
    ]
    taxable_total = _q(sum(line_taxables, Decimal("0")))
    tax_total = _q(sum(line_taxes, Decimal("0")))
    grand_total = _q(
        taxable_total + tax_total + body.shipping_total + body.other_charges + body.round_off
    )

    purchase = Purchase(
        business_id=business.id,
        supplier_id=supplier.id,
        invoice_no=body.invoice_no,
        invoice_date=body.invoice_date,
        po_no=body.po_no,
        taxable_total=taxable_total,
        tax_total=tax_total,
        shipping_total=body.shipping_total,
        other_charges=body.other_charges,
        round_off=body.round_off,
        grand_total=grand_total,
        notes=body.notes,
        origin="manual",
        status="posted",
        doc_type="invoice",
    )
    db.add(purchase)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise DuplicatePurchaseError(
            "a purchase with this invoice number already exists for this supplier"
        ) from None

    for sr_no, ((li, product), line_taxable) in enumerate(zip(resolved, line_taxables), start=1):
        db.add(
            PurchaseLineItem(
                purchase_id=purchase.id,
                sr_no=sr_no,
                product_id=product.id,
                raw_description=li.product_name or product.name,
                hsn_sac=li.hsn_sac or product.hsn_sac,
                qty=li.qty,
                uom=li.uom,
                price=li.price,
                discount=li.discount,
                gst_rate=li.gst_rate,
                line_total=line_taxable,
            )
        )
        apply_stock_movement(
            db, product, delta_qty=li.qty, reason="purchase", ref_type="purchase", ref_id=purchase.id
        )

    db.flush()
    return purchase
