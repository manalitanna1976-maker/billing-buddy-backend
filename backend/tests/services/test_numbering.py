from app.models import Business
from app.services.numbering import next_invoice_number


def test_next_invoice_number_increments_sequence(db_session):
    business = Business(name="Dattani Steel", invoice_prefix="INV-", invoice_postfix="", next_invoice_seq=89)
    db_session.add(business)
    db_session.commit()

    first = next_invoice_number(db_session, business)
    db_session.commit()
    second = next_invoice_number(db_session, business)
    db_session.commit()

    assert first == "INV-89"
    assert second == "INV-90"


def test_next_invoice_number_applies_postfix(db_session):
    business = Business(name="Dattani Steel", invoice_prefix="", invoice_postfix="/26-27", next_invoice_seq=1)
    db_session.add(business)
    db_session.commit()

    assert next_invoice_number(db_session, business) == "1/26-27"
