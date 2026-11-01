"""Choosing the AI provider from configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from app.ai import AIProvider, AIUnavailableError, FakeAIProvider, build_ai_provider
from app.core.config import Settings

FAKE_KEY = "test-key-not-a-real-secret"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore the developer's shell environment and .env file."""
    for var in ("AI_PROVIDER", "AI_MODEL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_default_is_fake_and_needs_no_key() -> None:
    config = settings()

    assert config.ai_provider == "fake"
    assert config.anthropic_api_key is None
    assert isinstance(build_ai_provider(config), FakeAIProvider)


def test_provider_is_selected_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    assert settings().ai_provider == "anthropic"

    monkeypatch.setenv("AI_PROVIDER", "fake")
    assert isinstance(build_ai_provider(settings()), FakeAIProvider)


@pytest.mark.parametrize("value", ["Fake", " FAKE ", "fake\n"])
def test_provider_name_is_case_and_whitespace_insensitive(value: str) -> None:
    assert settings(ai_provider=value).ai_provider == "fake"


@pytest.mark.parametrize("value", ["openai", "", "claude", "fake-ai"])
def test_unknown_provider_fails_with_a_clear_message(value: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings(ai_provider=value)

    message = str(exc_info.value)
    assert "ai_provider" in message
    assert "'fake' or 'anthropic'" in message


@pytest.mark.parametrize("key", [None, "", "   "])
def test_anthropic_without_key_is_a_clear_unavailable_error(key) -> None:
    config = settings(ai_provider="anthropic", anthropic_api_key=key)

    with pytest.raises(AIUnavailableError) as exc_info:
        build_ai_provider(config)

    assert exc_info.value.status_code == 503
    assert "ANTHROPIC_API_KEY" in exc_info.value.detail
    assert "AI_PROVIDER=fake" in exc_info.value.detail


def test_anthropic_is_not_available_yet_and_never_leaks_the_key() -> None:
    config = settings(ai_provider="anthropic", anthropic_api_key=FAKE_KEY)

    with pytest.raises(AIUnavailableError) as exc_info:
        build_ai_provider(config)

    assert "not available yet" in exc_info.value.detail
    assert FAKE_KEY not in exc_info.value.detail
    assert FAKE_KEY not in str(exc_info.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_key_from_env_file_means_not_set(monkeypatch: pytest.MonkeyPatch, blank: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", blank)  # .env.example ships ANTHROPIC_API_KEY=
    assert settings().anthropic_api_key is None


class TestApiKeyIsSecret:
    """M2: the key is a SecretStr and never appears in representations or messages."""

    @pytest.fixture
    def config(self) -> Settings:
        return settings(ai_provider="anthropic", anthropic_api_key=FAKE_KEY)

    def test_key_is_a_secret_str(self, config: Settings) -> None:
        assert isinstance(config.anthropic_api_key, SecretStr)
        # Readable only on purpose, by code that sends it to the provider.
        assert config.anthropic_api_key.get_secret_value() == FAKE_KEY

    @pytest.mark.parametrize(
        "render",
        [repr, str, lambda c: str(c.model_dump()), lambda c: c.model_dump_json()],
        ids=["repr", "str", "model_dump", "model_dump_json"],
    )
    def test_representations_do_not_expose_the_key(self, config: Settings, render) -> None:
        text = render(config)
        assert FAKE_KEY not in text
        assert "**********" in text

    def test_key_from_environment_is_masked_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
        assert FAKE_KEY not in repr(settings())

    def test_validation_errors_do_not_expose_the_key(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            settings(ai_provider="openai", anthropic_api_key=FAKE_KEY)
        assert FAKE_KEY not in str(exc_info.value)

    def test_provider_errors_do_not_expose_the_key(self, config: Settings) -> None:
        with pytest.raises(AIUnavailableError) as exc_info:
            build_ai_provider(config)
        assert FAKE_KEY not in str(exc_info.value)
        assert FAKE_KEY not in exc_info.value.detail


def test_any_object_with_the_right_methods_satisfies_the_protocol() -> None:
    class Stub:
        name = "stub"

        def parse_transaction(self, request): ...

        def generate_insights(self, request): ...

    assert isinstance(Stub(), AIProvider)
    assert not isinstance(object(), AIProvider)
