"""
Shared pytest fixtures/config.

The whole suite is designed to run with zero setup: `pip install -r
requirements.txt && pytest` from `backend/`, no database, no API key,
nothing. That's only possible because the vast majority of what actually
broke this build (see README.md's dated bug list) was a pure computation or
prompt-construction bug — fixable, and testable, entirely in Python with no
network call at all. `pytest.ini`'s `integration` marker is the honest
exception: a handful of the highest-value fixes are prompt-*wording*
regressions (an LLM narrating two correct numbers in the wrong order, an
over-hedging disclaimer) that genuinely can't be verified without a real
call — those are marked explicitly and skipped automatically here unless
OPENAI_API_KEY is actually set, rather than either silently costing money
in CI or silently not existing at all.

Note on what "set" means in practice: config.py calls load_dotenv() at
import time, so this file imports config directly below (not just for its
own use) specifically to guarantee os.environ is populated from
backend/.env before pytest_collection_modifyitems runs, regardless of
which test modules happen to get collected or in what order. That used to
be an incidental side effect of *some* test module transitively importing
config first — real on a dev machine where enough other files still do,
but a genuine, order-dependent false-skip risk for a test run limited to
files that don't happen to import anything config-touching at module level
(route-level test files, e.g. test_budget_routes.py, are exactly that:
they only reach app code inside the `client` fixture, which runs per-test,
after collection-time marks are already decided). Importing config here
removes the dependency on incidental import order entirely.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config as _app_config  # noqa: F401 — import side effect only (triggers load_dotenv()); aliased to avoid shadowing pytest_collection_modifyitems's own `config` (pytest's Config object) parameter below


def pytest_collection_modifyitems(config, items):
    if os.getenv("OPENAI_API_KEY"):
        return  # real key present — let integration tests run
    skip_integration = pytest.mark.skip(reason="OPENAI_API_KEY not set — run with a real key to include this")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# --- Route-level test fixtures ---------------------------------------------
#
# Endpoint tests (test_*_routes.py) still keep this suite's "zero setup"
# promise (module docstring above): each test gets a fresh in-memory SQLite
# database instead of the real Postgres config.DATABASE_URL, via FastAPI's
# dependency_overrides on get_db — nothing to install, nothing reachable
# over the network, no state shared between tests. StaticPool + a single
# shared connection so the one in-memory database persists across the
# several queries a single test request can trigger (a bare `sqlite:///
# :memory:` engine hands out a NEW empty database per connection, which
# would otherwise make every query after the first see empty tables).
#
# SQLite instead of a second real Postgres purely for these tests: the ORM
# models (db/models.py) use only portable SQLAlchemy types (String,
# LargeBinary, DateTime, ForeignKey) — nothing pgvector-specific — so there's
# nothing SQLite can't represent, and it needs no server, no docker, no
# extension setup, matching every other test file's zero-setup bar.


@pytest.fixture
def client():
    from api.main import app
    from db.database import Base, get_db

    test_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()


@pytest.fixture
def auth_headers(client):
    """Registers a fresh test user against the same in-memory database
    `client` is bound to, and returns an Authorization header for it."""
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/auth/register", json={"email": email, "password": "TestPass123"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_auth_headers(client):
    """Factory version of auth_headers — for tests that need two or more
    distinct users on the same in-memory database (e.g. verifying one
    user's saved data is invisible to another)."""

    def _make() -> dict[str, str]:
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        response = client.post("/auth/register", json={"email": email, "password": "TestPass123"})
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _make
