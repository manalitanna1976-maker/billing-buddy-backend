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
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # The login rate limiter (app/rate_limit.py) keeps its counters in a
    # module-level in-memory dict. Without resetting it, one test's
    # failed-login hammering would bleed into and break unrelated tests.
    rate_limit.reset_all_state()
    yield
    rate_limit.reset_all_state()


@pytest.fixture(autouse=True)
def _reset_token_revocation():
    # Same reasoning as _reset_rate_limiter: app/token_revocation.py's store
    # is module-level in-memory state, and would otherwise leak a logged-out
    # token's revocation across tests.
    token_revocation.reset_all_state()
    yield
    token_revocation.reset_all_state()


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()
