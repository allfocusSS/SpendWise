from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Point plain PostgreSQL URLs at the installed driver (psycopg 3).

    Hosts often hand out postgres://... or postgresql://...; SQLAlchemy reads both as psycopg2,
    which is not installed. Other URLs (sqlite, postgresql+psycopg) are returned unchanged.
    """
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (and an optional .env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors never echo values: DATABASE_URL can contain a password.
        hide_input_in_errors=True,
    )

    app_name: str = "SpendWise"
    environment: Literal["local", "test", "production"] = "local"
    # SQLite for local development and tests; PostgreSQL in production, e.g.
    # postgresql+psycopg://USER:PASSWORD@HOST:5432/spendwise. repr=False keeps the password out
    # of repr(settings) and anything that logs it.
    database_url: str = Field(default="sqlite:///./spendwise.db", repr=False)
    currency: str = "KZT"
    # Directory of the built frontend (Vite `dist`). Set in the Docker image; unset locally,
    # where the Vite dev server serves the frontend.
    frontend_dist: Path | None = None

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

    @field_validator("anthropic_api_key", "frontend_dist", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # ANTHROPIC_API_KEY= (empty, as in .env.example) means "not set"; same for FRONTEND_DIST.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        return normalize_database_url(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _production_uses_postgresql(self) -> Self:
        # A production container on SQLite would keep data in one file inside the container.
        if self.environment == "production" and not self.database_url.startswith("postgresql"):
            raise ValueError(
                "ENVIRONMENT=production requires a PostgreSQL DATABASE_URL "
                "(postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
