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
