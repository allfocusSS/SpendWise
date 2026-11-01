"""Waiting for the database at startup (app.core.wait_for_db)."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.wait_for_db import main, wait_for_database

PASSWORD = "not-a-real-password"


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Let each test point DATABASE_URL somewhere, with fresh settings."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def use(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_returns_at_once_when_the_database_answers(
    database_url, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    use(monkeypatch, f"sqlite:///{tmp_path / 'ready.db'}")

    assert wait_for_database(timeout=5) is True
    assert "Database is ready (attempt 1)" in capsys.readouterr().out


def test_gives_up_after_the_timeout_without_printing_the_url(
    database_url, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    url = f"postgresql+psycopg://spendwise:{PASSWORD}@127.0.0.1:{unused_port()}/spendwise"
    use(monkeypatch, url)

    assert wait_for_database(timeout=0.6, interval=0.2) is False

    out = capsys.readouterr().out
    assert "Waiting for the database (attempt 1)" in out
    assert "Database still unavailable after" in out
    assert PASSWORD not in out


def test_command_exit_codes(database_url, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    use(monkeypatch, f"sqlite:///{tmp_path / 'ready.db'}")
    assert main() == 0

    use(monkeypatch, f"postgresql+psycopg://u:{PASSWORD}@127.0.0.1:{unused_port()}/d")
    monkeypatch.setenv("DB_WAIT_TIMEOUT", "0.3")
    assert main() == 1
