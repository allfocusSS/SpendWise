"""The app runs without any AI credentials, whatever AI provider is configured."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai import AIUnavailableError, FakeAIProvider, get_ai_provider
from app.core.config import get_settings
from app.core.db import get_db
from app.main import create_app


@pytest.fixture
def ai_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Explicit AI configuration for one test, independent of the developer's shell or .env.

    Environment variables take priority over a .env file, so setting them here (rather than
    deleting them) means a local backend/.env cannot change the outcome.
    """
    monkeypatch.setenv("AI_PROVIDER", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # blank = not set
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_default_provider_works_with_no_key(ai_env: pytest.MonkeyPatch) -> None:
    assert isinstance(get_ai_provider(), FakeAIProvider)


def test_local_env_file_cannot_change_the_test_configuration(
    ai_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Simulate a developer's .env that selects Anthropic with a key.
    (tmp_path / ".env").write_text("AI_PROVIDER=anthropic\nANTHROPIC_API_KEY=local-dev-value\n")
    ai_env.chdir(tmp_path)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.ai_provider == "fake"
    assert settings.anthropic_api_key is None
    assert isinstance(get_ai_provider(), FakeAIProvider)


def test_app_starts_and_serves_data_when_ai_is_misconfigured(
    ai_env: pytest.MonkeyPatch, client: TestClient
) -> None:
    ai_env.setenv("AI_PROVIDER", "anthropic")  # selected, but no ANTHROPIC_API_KEY
    get_settings.cache_clear()  # the `client` fixture already cached the default settings

    app = create_app()
    app.dependency_overrides[get_db] = client.app.dependency_overrides[get_db]
    misconfigured = TestClient(app)

    # Non-AI features are unaffected...
    assert misconfigured.get("/api/health").status_code == 200
    assert misconfigured.get("/api/categories").status_code == 200
    assert misconfigured.get("/api/analytics/summary").status_code == 200
    # ...and only asking for the AI provider reports the problem.
    with pytest.raises(AIUnavailableError, match="ANTHROPIC_API_KEY"):
        get_ai_provider()


def test_ai_unavailable_error_becomes_a_503_json_response(client: TestClient) -> None:
    app = client.app

    @app.get("/api/_test/ai")
    def _needs_ai() -> None:
        raise AIUnavailableError("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")

    response = client.get("/api/_test/ai")

    assert response.status_code == 503
    assert response.json() == {"detail": "AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY."}


def test_invalid_ai_provider_in_the_shell_does_not_break_the_test_suite() -> None:
    # conftest.py sets AI_PROVIDER=fake before the app is imported, so a developer's invalid
    # value (or a real key) cannot crash collection or leak into tests. Run a child pytest with a
    # hostile environment to prove it.
    backend_dir = Path(__file__).resolve().parents[2]
    env = {**os.environ, "AI_PROVIDER": "openai", "ANTHROPIC_API_KEY": "shell-value-not-a-secret"}
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/integration/test_health.py",
        ],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
