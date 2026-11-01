from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (and an optional .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SpendWise"
    environment: Literal["local", "test", "production"] = "local"
    database_url: str = "sqlite:///./spendwise.db"
    currency: str = "KZT"

    # AI: the app must work without a real key, so "fake" is the default.
    # An unknown AI_PROVIDER value fails at startup with a message listing the allowed values.
    ai_provider: Literal["fake", "anthropic"] = "fake"
    ai_model: str = "claude-opus-5-5"
    # SecretStr: shown as '**********' in repr(), str(), model_dump() and model_dump_json().
    # Only the provider that sends the key may call .get_secret_value().
    anthropic_api_key: SecretStr | None = None

    @field_validator("ai_provider", mode="before")
    @classmethod
    def _normalise_ai_provider(cls, value: object) -> object:
        # Accept "Fake", " FAKE " etc.; the Literal check above still rejects unknown names.
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value: object) -> object:
        # ANTHROPIC_API_KEY= (empty, as in .env.example) means "not set".
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
