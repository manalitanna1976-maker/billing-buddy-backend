from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_business
from app.models import Business
from app.schemas.business import BusinessRead, BusinessUpdate
from app.storage import save_upload

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
