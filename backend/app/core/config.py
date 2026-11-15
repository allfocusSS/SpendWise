import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Where this process runs. Set explicitly by each deployment (APP_ENV), never guessed from a
# hostname: development is Render, production is AWS (docs/environments.md). Both are deployed
# environments and get the same hardening (PostgreSQL only, Secure cookies over plain HTTP).
AppEnv = Literal["local", "test", "development", "production"]
DEPLOYED_ENVIRONMENTS = frozenset({"development", "production"})
# A version is always a full Git commit SHA, never a branch name or an abbreviation.
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


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
    # APP_ENV. Running from source defaults to local; the Docker image sets production, and
    # every deployment sets its own value (render.yaml, compose files). The old ENVIRONMENT
    # variable is not read: Render keeps variables a Blueprint no longer lists, so a leftover
    # ENVIRONMENT=production there must not change anything.
    app_env: AppEnv = "local"
    # The exact commit this process runs, reported by GET /api/meta. APP_VERSION is set by the
    # deployment (on AWS, the deploy wrapper passes the SHA it deploys); without it, Render's
    # RENDER_GIT_COMMIT is used. Either must be a full 40-character lowercase SHA.
    app_version: str | None = None
    render_git_commit: str | None = None
    # SQLite for local development and tests; PostgreSQL when deployed, e.g.
    # postgresql+psycopg://USER:PASSWORD@HOST:5432/spendwise. repr=False keeps the password out
    # of repr(settings) and anything that logs it.
    database_url: str = Field(default="sqlite:///./spendwise.db", repr=False)
    currency: str = "KZT"
    # Directory of the built frontend (Vite `dist`). Set in the Docker image; unset locally,
    # where the Vite dev server serves the frontend.
    frontend_dist: Path | None = None

    # Sign-in sessions (HttpOnly cookie). A cookie sent over HTTPS is always Secure. For plain
    # HTTP requests, SESSION_COOKIE_SECURE decides: unset means Secure in development and
    # production only; false allows a production build on http://localhost (the local Compose
    # stack sets it). See secure_cookie().
    session_cookie_secure: bool | None = None
    session_ttl_days: int = Field(default=14, ge=1, le=90)

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

    @field_validator(
        "anthropic_api_key",
        "frontend_dist",
        "session_cookie_secure",
        "app_version",
        "render_git_commit",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # ANTHROPIC_API_KEY= (empty, as in .env.example) means "not set"; same for the others.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("app_version", "render_git_commit")
    @classmethod
    def _full_commit_sha(cls, value: str | None) -> str | None:
        if value is not None and not COMMIT_SHA.fullmatch(value):
            raise ValueError("must be a full 40-character lowercase Git commit SHA")
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        return normalize_database_url(value) if isinstance(value, str) else value

    def secure_cookie(self, request_is_https: bool) -> bool:
        """Whether the session cookie gets the Secure attribute (HTTPS only).

        A request that arrived over HTTPS (directly, or as reported by a trusted proxy's
        X-Forwarded-Proto) always gets a Secure cookie, so a setting meant for local plain HTTP
        can never weaken a public HTTPS deployment.
        """
        if request_is_https:
            return True
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.is_deployed

    @property
    def is_deployed(self) -> bool:
        """Development (Render) or production (AWS), as opposed to local or test."""
        return self.app_env in DEPLOYED_ENVIRONMENTS

    @property
    def version(self) -> str | None:
        """The exact commit this process runs: APP_VERSION, else RENDER_GIT_COMMIT, else None."""
        return self.app_version or self.render_git_commit

    def resource_attributes(self) -> dict[str, str]:
        """This deployment as OpenTelemetry resource attributes, for telemetry to come.

        deployment.environment is APP_ENV and service.version the exact commit, so telemetry
        from development and production never mixes. No hostnames or infrastructure IDs.
        """
        attributes = {"service.name": "spendwise", "deployment.environment": self.app_env}
        if self.version:
            attributes["service.version"] = self.version
        return attributes

    @model_validator(mode="after")
    def _deployed_environments_use_postgresql(self) -> Self:
        # A deployed container on SQLite would keep data in one file inside the container.
        if self.is_deployed and not self.database_url.startswith("postgresql"):
            raise ValueError(
                f"APP_ENV={self.app_env} requires a PostgreSQL DATABASE_URL "
                "(postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
