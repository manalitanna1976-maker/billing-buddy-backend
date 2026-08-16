from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business


def next_invoice_number(db: Session, business: Business) -> str:
    locked = db.execute(
        select(Business).where(Business.id == business.id).with_for_update()
    ).scalar_one()

    seq = locked.next_invoice_seq
    number = f"{locked.invoice_prefix}{seq}{locked.invoice_postfix}"

    locked.next_invoice_seq = seq + 1
    business.next_invoice_seq = seq + 1

    return number
