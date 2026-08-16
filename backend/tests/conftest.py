import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://billing:billing@localhost:5544/billing_buddy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine, SessionLocal


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()
