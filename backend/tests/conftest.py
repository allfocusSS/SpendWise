from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import build_engine, get_db
from app.main import create_app
from app.models import Base
from app.seed import seed_default_categories


@pytest.fixture
def engine() -> Iterator[Engine]:
    """A fresh in-memory SQLite database per test, with default categories seeded."""
    engine = build_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_default_categories(session)
    yield engine
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
