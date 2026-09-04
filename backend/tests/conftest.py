import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://billing:billing@localhost:5544/billing_buddy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SECRET_ENCRYPTION_KEY", "qdEOcT2pkbVQ63tsXIEv6m5l0WILEJ_gMBWTm-_NHyE=")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine, SessionLocal
from app import rate_limit, token_revocation


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # rate_limit / token_revocation state now lives in Postgres tables rather
    # than in-memory dicts. The drop_all/create_all above already leaves them
    # empty, but keep an explicit seam so the intent survives any change to
    # the reset strategy, and so a leaked row from an aborted test is cleared.
    s = SessionLocal()
    try:
        rate_limit.reset_all_state(s)
        token_revocation.reset_all_state(s)
    finally:
        s.close()
    yield


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()
