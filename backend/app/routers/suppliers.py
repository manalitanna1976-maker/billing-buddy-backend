import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_business
from app.models import Business, Supplier
from app.schemas.inventory import SupplierCreate, SupplierRead, SupplierUpdate
from app.services.inventory import DuplicateNameError, create_supplier

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _get_owned_or_404(db: Session, business: Business, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None or supplier.business_id != business.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


@router.get("", response_model=list[SupplierRead])
def list_suppliers(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    query = db.query(Supplier).filter(Supplier.business_id == business.id)
    if q:
        query = query.filter(Supplier.name.ilike(f"%{q}%"))
    return query.order_by(Supplier.name).offset(offset).limit(limit).all()


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier_route(
    body: SupplierCreate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    try:
        supplier = create_supplier(db, business, body)
    except DuplicateNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    db.commit()
    db.refresh(supplier)
    return supplier


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(
    supplier_id: uuid.UUID,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    return _get_owned_or_404(db, business, supplier_id)


@router.put("/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
):
    supplier = _get_owned_or_404(db, business, supplier_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    db.commit()
    db.refresh(supplier)
    return supplier
