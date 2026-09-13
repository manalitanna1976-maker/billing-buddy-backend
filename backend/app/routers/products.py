import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Product, StockMovement
from app.schemas.inventory import (
    ProductCreate,
    ProductRead,
    ProductUpdate,
    StockAdjustment,
    StockMovementRead,
)
from app.services.inventory import DuplicateNameError, apply_stock_movement, create_product

router = APIRouter(prefix="/products", tags=["products"])


def _get_owned_or_404(db: Session, business: Business, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("", response_model=list[ProductRead])
def list_products(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    query = db.query(Product).filter(Product.business_id == business.id)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    return query.order_by(Product.name).offset(offset).limit(limit).all()


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product_route(
    body: ProductCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    try:
        product = create_product(db, business, body)
    except DuplicateNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, business, product_id)


@router.put("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    product = _get_owned_or_404(db, business, product_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/adjust-stock", response_model=ProductRead)
def adjust_stock(
    product_id: uuid.UUID,
    body: StockAdjustment,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    product = _get_owned_or_404(db, business, product_id)
    apply_stock_movement(
        db, product, delta_qty=body.delta_qty, reason="manual_adjustment", note=body.note
    )
    db.commit()
    db.refresh(product)
    return product


@router.get("/{product_id}/stock-movements", response_model=list[StockMovementRead])
def list_stock_movements(
    product_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    _get_owned_or_404(db, business, product_id)
    return (
        db.query(StockMovement)
        .filter(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
