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
