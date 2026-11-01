import os

# Test configuration is fixed BEFORE the app is imported: app.core.db reads the settings at import
# time, so an invalid AI_PROVIDER (or a real key) in the developer's shell or backend/.env must not
# reach the tests. Environment variables take priority over .env, so these values always win.
# Tests that check provider selection set their own values with monkeypatch.
os.environ["AI_PROVIDER"] = "fake"
os.environ["ANTHROPIC_API_KEY"] = ""
# The backend serves no frontend in tests unless a test mounts one (see test_frontend_serving.py).
os.environ["FRONTEND_DIST"] = ""

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, make_url  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.config import normalize_database_url  # noqa: E402
from app.core.db import build_engine, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from app.seed import seed_default_categories  # noqa: E402

# Tests use a fresh in-memory SQLite database by default. To run the same suite on PostgreSQL:
#   TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/spendwise_test uv run pytest
# Every test creates and then drops all tables, so the database name must contain "test".
TEST_DATABASE_URL = normalize_database_url(os.environ.get("TEST_DATABASE_URL", ""))
if TEST_DATABASE_URL and "test" not in (make_url(TEST_DATABASE_URL).database or ""):
    raise pytest.UsageError(
        "TEST_DATABASE_URL must name a throwaway database containing 'test' (tables are dropped)."
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    """A fresh database per test (in-memory SQLite, or TEST_DATABASE_URL), defaults seeded."""
    if TEST_DATABASE_URL:
        engine = build_engine(TEST_DATABASE_URL)
        Base.metadata.drop_all(engine)  # in case an interrupted run left tables behind
    else:
        engine = build_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_default_categories(session)
    yield engine
    if TEST_DATABASE_URL:
        Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> TestClient:
    app = create_app()
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_test_db() -> Iterator[Session]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_test_db
    return TestClient(app)


@pytest.fixture
def category_ids(client: TestClient) -> dict[str, int]:
    """Map of default category name -> id, e.g. category_ids["Groceries"]."""
    return {c["name"]: c["id"] for c in client.get("/api/categories").json()}
