import os

# Tests never touch the real Postgres: force an in-memory SQLite DB before app import.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["INTERNAL_SECRET"] = "test-internal"
os.environ["ALLOW_RESET"] = "true"
os.environ["DEMO_EXTRA_ORDERS"] = "0"  # unit tests use the 5 hand-written orders
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("SYSTEM_TOKEN_SECRET", "test-system-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from opspilot_common.auth import create_access_token  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)  # fresh seeded DB per test
    with TestClient(app) as c:
        yield c


def _headers(user_id: int, username: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, username, role)}"}


@pytest.fixture
def alice():
    return _headers(1, "alice", "customer")


@pytest.fixture
def bob():
    return _headers(2, "bob", "customer")


@pytest.fixture
def staff():
    return _headers(3, "staff1", "staff")
