from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (and an optional .env file)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SpendWise"
    environment: Literal["local", "test", "production"] = "local"
    database_url: str = "sqlite:///./spendwise.db"
    currency: str = "KZT"

    # AI: the app must work without a real key, so "fake" is the default.
    ai_provider: Literal["fake", "anthropic"] = "fake"
    ai_model: str = "claude-opus-5-5"
    anthropic_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
