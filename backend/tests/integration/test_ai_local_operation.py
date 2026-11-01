"""The app runs without any AI credentials, whatever AI provider is configured."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.ai import AIUnavailableError, FakeAIProvider, get_ai_provider
from app.core.config import get_settings
from app.core.db import get_db
from app.main import create_app


@pytest.fixture
def ai_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Set AI environment variables for one test and reset the cached settings around it."""
    for var in ("AI_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_default_provider_works_with_no_key(ai_env: pytest.MonkeyPatch) -> None:
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
