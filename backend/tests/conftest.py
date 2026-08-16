import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://billing:billing@localhost:5544/billing_buddy_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)
