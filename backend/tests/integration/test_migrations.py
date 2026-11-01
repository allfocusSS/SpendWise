"""Alembic migrations must build exactly the schema the models describe, on every database."""

import os
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import get_settings, normalize_database_url
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = normalize_database_url(os.environ.get("TEST_DATABASE_URL", ""))


def make_config(db_url: str | None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    if db_url is not None:
        config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return config


@pytest.fixture(params=["sqlite", "postgresql"])
def db_url(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'migrations.db'}"
    if not TEST_DATABASE_URL.startswith("postgresql"):
        pytest.skip("set TEST_DATABASE_URL to a PostgreSQL database to run this")
    return TEST_DATABASE_URL


def test_upgrade_matches_models_and_downgrade_cleans_up(db_url: str) -> None:
    config = make_config(db_url)
    engine = create_engine(db_url)
    assert inspect(engine).get_table_names() == [], "migrations need an empty database"

    try:
        command.upgrade(config, "head")
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert diff == [], f"Models and migrations are out of sync: {diff}"

        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        # Leave a shared PostgreSQL test database empty for the next test.
        with engine.begin() as connection:
            for table in ("transactions", "categories", "alembic_version"):
                connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


def test_database_url_from_settings_may_contain_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # URL-encoded passwords contain "%"; alembic.ini interpolation must not choke on them.
    db_file = tmp_path / "100%.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    try:
        command.upgrade(make_config(None), "head")
    finally:
        get_settings.cache_clear()

    engine = create_engine(f"sqlite:///{db_file}")
    assert {"categories", "transactions"} <= set(inspect(engine).get_table_names())
    engine.dispose()
