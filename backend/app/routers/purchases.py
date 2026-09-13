import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Purchase, Supplier
from app.schemas.purchase import PurchaseCreate, PurchaseListItem, PurchaseRead
from app.services.purchases import (
    DuplicatePurchaseError,
    ProductNotFoundError,
    SupplierNotFoundError,
    create_purchase_for_business,
)

router = APIRouter(prefix="/purchases", tags=["purchases"])


def _get_owned_or_404(db: Session, business: Business, purchase_id: uuid.UUID) -> Purchase:
    purchase = (
        db.query(Purchase)
        .options(joinedload(Purchase.line_items))
        .filter(Purchase.id == purchase_id)
        .first()
    )
    if purchase is None or purchase.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase not found")
    return purchase


@router.get("", response_model=list[PurchaseListItem])
def list_purchases(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Purchase, Supplier.name.label("supplier_name"))
        .join(Supplier, Purchase.supplier_id == Supplier.id, isouter=True)
        .where(Purchase.business_id == business.id)
        .order_by(Purchase.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": p.id,
            "invoice_no": p.invoice_no,
            "po_no": p.po_no,
            "invoice_date": p.invoice_date,
            "supplier_name": supplier_name,
            "grand_total": p.grand_total,
            "status": p.status,
            "origin": p.origin,
        }
        for p, supplier_name in rows
    ]


@router.post("", response_model=PurchaseRead, status_code=status.HTTP_201_CREATED)
def create_purchase(
    body: PurchaseCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    try:
        purchase = create_purchase_for_business(db, business, body)
    except SupplierNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found") from None
    except ProductNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found") from None
    except DuplicatePurchaseError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    db.commit()
    db.refresh(purchase)
    return purchase


@router.get("/{purchase_id}", response_model=PurchaseRead)
def get_purchase(
    purchase_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, business, purchase_id)
