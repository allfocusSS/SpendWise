"""Alembic migrations must build exactly the schema the models describe."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]


def make_config(db_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def test_upgrade_matches_models_and_downgrade_cleans_up(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = make_config(db_url)
    engine = create_engine(db_url)

    command.upgrade(config, "head")
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"Models and migrations are out of sync: {diff}"

    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
