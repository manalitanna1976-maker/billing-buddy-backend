import uuid

from app.models import Business, User


def test_create_business_and_user(db_session):
    business = Business(name="Dattani Steel", state="Gujarat")
    db_session.add(business)
    db_session.flush()

    user = User(
        business_id=business.id,
        email="owner@dattanisteel.test",
        password_hash="hashed",
    )
    db_session.add(user)
    db_session.commit()

    assert isinstance(business.id, uuid.UUID)
    assert user.business_id == business.id
