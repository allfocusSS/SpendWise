"""Alembic migrations must build exactly the schema the models describe, on every database."""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text

from alembic import command
from app.core.config import get_settings, normalize_database_url
from app.core.db import MIGRATION_LOCK
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


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    engine = create_engine(db_url)
    assert inspect(engine).get_table_names() == [], "migrations need an empty database"
    yield engine
    # Leave a shared PostgreSQL test database empty for the next test.
    with engine.begin() as connection:
        for table in ("transactions", "categories", "sessions", "users", "alembic_version"):
            connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
    engine.dispose()


def test_upgrade_matches_models_and_downgrade_cleans_up(db_url: str, engine: Engine) -> None:
    config = make_config(db_url)

    command.upgrade(config, "head")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"Models and migrations are out of sync: {diff}"

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}


def test_concurrent_upgrades_take_turns(db_url: str, engine: Engine) -> None:
    # Two app containers starting at once (replicas, overlapping deploys) both run
    # `alembic upgrade head`. On PostgreSQL an advisory lock makes the second wait and then find
    # nothing to do, instead of failing on tables the first one just created.
    if not db_url.startswith("postgresql"):
        pytest.skip("the migration lock is PostgreSQL-only; SQLite has a single writer anyway")
    env = {**os.environ, "DATABASE_URL": db_url}
    command_line = [sys.executable, "-m", "alembic", "upgrade", "head"]

    # Hold the lock while both processes start, so they really race once it is released.
    with engine.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK})
        processes = [
            subprocess.Popen(
                command_line,
                cwd=BACKEND_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for _ in range(2)
        ]
        time.sleep(2)  # both connect and queue up behind the lock
        holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK})
        holder.commit()
    outputs = [process.communicate(timeout=120)[0] for process in processes]

    assert [process.returncode for process in processes] == [0, 0], outputs
    assert sum("Running upgrade 0001 -> 0002" in output for output in outputs) == 1, outputs
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).all() == [
            ("0002",)
        ]


# --- 0002: data created before accounts existed -------------------------------------------------

NOW = "2026-10-01 00:00:00"


def add_0001_category(engine: Engine, name: str, is_default: bool) -> int:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO categories (name, type, color, is_default, created_at, updated_at) "
                "VALUES (:name, 'expense', '#000000', :is_default, :now, :now)"
            ),
            {"name": name, "is_default": is_default, "now": NOW},
        )
        return connection.execute(
            text("SELECT id FROM categories WHERE name = :name"), {"name": name}
        ).scalar_one()


def add_0001_transaction(engine: Engine, category_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO transactions (amount_cents, type, category_id, description, "
                "occurred_on, source, created_at, updated_at) VALUES "
                "(100, 'expense', :category_id, 'old', '2026-10-01', 'manual', :now, :now)"
            ),
            {"category_id": category_id, "now": NOW},
        )


def version(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


@pytest.mark.parametrize("legacy", ["transaction", "custom category"])
def test_upgrade_refuses_data_without_an_owner(db_url: str, engine: Engine, legacy: str) -> None:
    config = make_config(db_url)
    command.upgrade(config, "0001")
    groceries = add_0001_category(engine, "Groceries", is_default=True)
    if legacy == "transaction":
        add_0001_transaction(engine, groceries)
    else:
        add_0001_category(engine, "Pets", is_default=False)

    with pytest.raises(RuntimeError, match="cannot be assigned to a user automatically"):
        command.upgrade(config, "head")

    # Nothing was changed or deleted.
    assert version(engine) == "0001"
    assert "users" not in inspect(engine).get_table_names()
    assert count(engine, "categories") == (1 if legacy == "transaction" else 2)
    assert count(engine, "transactions") == (1 if legacy == "transaction" else 0)


def test_upgrade_replaces_global_defaults_with_per_user_ones(db_url: str, engine: Engine) -> None:
    config = make_config(db_url)
    command.upgrade(config, "0001")
    for name in ("Groceries", "Transport"):
        add_0001_category(engine, name, is_default=True)

    command.upgrade(config, "head")

    assert version(engine) == "0002"
    assert count(engine, "categories") == 0  # each new account gets its own defaults
    assert {"users", "sessions"} <= set(inspect(engine).get_table_names())


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
