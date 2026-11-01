"""DATABASE_URL handling: SQLite locally, PostgreSQL (psycopg 3) in production."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, normalize_database_url
from app.core.db import build_engine

PASSWORD = "not-a-real-password"
PG_URL = f"postgresql+psycopg://spendwise:{PASSWORD}@db.example:5432/spendwise"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore the developer's shell environment and .env file."""
    for var in ("ENVIRONMENT", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_default_is_local_sqlite() -> None:
    assert settings().database_url == "sqlite:///./spendwise.db"


def test_database_url_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    assert settings().database_url == PG_URL


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("  postgresql://u:p@h/d\n", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("sqlite:///./spendwise.db", "sqlite:///./spendwise.db"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_plain_postgresql_urls_use_psycopg_3(given: str, expected: str) -> None:
    assert normalize_database_url(given) == expected
    assert settings(database_url=given).database_url == expected


@pytest.mark.parametrize("url", ["sqlite:///./spendwise.db", "sqlite:////app/data/x.db"])
def test_production_refuses_sqlite(url: str) -> None:
    with pytest.raises(ValidationError, match="requires a PostgreSQL DATABASE_URL"):
        settings(environment="production", database_url=url)


def test_production_accepts_postgresql() -> None:
    config = settings(environment="production", database_url="postgres://u:p@h/d")
    assert config.database_url == "postgresql+psycopg://u:p@h/d"


def test_password_is_not_in_repr() -> None:
    assert PASSWORD not in repr(settings(database_url=PG_URL))
    assert PASSWORD not in str(settings(database_url=PG_URL))


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "production", "database_url": f"sqlite:///{PASSWORD}.db"},
        {"environment": "staging", "database_url": PG_URL},
        {"ai_provider": "openai", "database_url": PG_URL},
    ],
)
def test_validation_errors_do_not_echo_the_database_url(values: dict) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings(**values)
    assert PASSWORD not in str(exc_info.value)


def test_postgresql_engine_uses_psycopg_and_pre_ping() -> None:
    engine = build_engine(PG_URL)  # no connection is made until first use

    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    assert engine.pool._pre_ping is True
    assert PASSWORD not in repr(engine)


def test_sqlite_engine_is_unchanged() -> None:
    engine = build_engine("sqlite://")

    assert engine.dialect.name == "sqlite"
    assert engine.pool._pre_ping is False
