"""APP_ENV and the deployed version: which environment this is and which commit it runs.

Development (Render) and production (AWS) set APP_ENV themselves (docs/environments.md); the
version comes from APP_VERSION, else Render's RENDER_GIT_COMMIT.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
OTHER_SHA = "1a87352a1a87352a1a87352a1a87352a1a87352a"
PG_URL = "postgresql+psycopg://spendwise:not-a-real-password@db.example:5432/spendwise"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore the developer's shell environment, .env file and the test suite's own values."""
    for var in ("APP_ENV", "ENVIRONMENT", "APP_VERSION", "RENDER_GIT_COMMIT", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_running_from_source_is_local_with_no_version() -> None:
    config = settings()
    assert config.app_env == "local"
    assert config.version is None
    assert not config.is_deployed


@pytest.mark.parametrize("app_env", ["local", "test", "development", "production"])
def test_app_env_comes_from_the_environment(monkeypatch, app_env: str) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    assert settings().app_env == app_env


@pytest.mark.parametrize(
    "value", ["staging", "prod", "Production", "dev", "PRODUCTION ", "", "development,production"]
)
def test_only_the_known_environments_are_accepted(monkeypatch, value: str) -> None:
    monkeypatch.setenv("APP_ENV", value)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    with pytest.raises(ValidationError, match="app_env"):
        settings()


@pytest.mark.parametrize(
    ("app_env", "deployed"),
    [("local", False), ("test", False), ("development", True), ("production", True)],
)
def test_development_and_production_are_the_deployed_environments(app_env, deployed) -> None:
    assert settings(app_env=app_env, database_url=PG_URL).is_deployed is deployed


def test_the_old_environment_variable_is_not_read(monkeypatch) -> None:
    # Render keeps variables that render.yaml no longer lists, so its old ENVIRONMENT=production
    # stays next to APP_ENV=development. It must not change anything.
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert settings().app_env == "local"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    assert settings().app_env == "development"


def test_the_environment_is_never_inferred_from_the_host(monkeypatch) -> None:
    for name, value in {
        "RENDER": "true",
        "RENDER_SERVICE_NAME": "spendwise",
        "RENDER_EXTERNAL_HOSTNAME": "spendwise-amyx.onrender.com",
        "HOSTNAME": "ip-10-0-0-1.ap-southeast-2.compute.internal",
        "SPENDWISE_SITE_ADDRESS": "54.79.77.189.nip.io",
    }.items():
        monkeypatch.setenv(name, value)
    assert settings().app_env == "local"


# --- Version -------------------------------------------------------------------------------


def test_app_version_is_the_version(monkeypatch) -> None:
    monkeypatch.setenv("APP_VERSION", SHA)
    assert settings().version == SHA


def test_render_git_commit_is_used_without_app_version(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", SHA)
    assert settings().version == SHA


def test_app_version_wins_over_render_git_commit(monkeypatch) -> None:
    monkeypatch.setenv("APP_VERSION", SHA)
    monkeypatch.setenv("RENDER_GIT_COMMIT", OTHER_SHA)
    assert settings().version == SHA


def test_an_empty_app_version_falls_back_to_render_git_commit(monkeypatch) -> None:
    # compose.yaml passes APP_VERSION=${APP_VERSION:-}, which is empty when nothing set it.
    monkeypatch.setenv("APP_VERSION", "")
    assert settings().version is None
    monkeypatch.setenv("RENDER_GIT_COMMIT", OTHER_SHA)
    assert settings().version == OTHER_SHA


@pytest.mark.parametrize("variable", ["APP_VERSION", "RENDER_GIT_COMMIT"])
@pytest.mark.parametrize(
    "value",
    [
        "main",
        "refs/heads/main",
        SHA[:7],
        SHA[:39],
        SHA + "0",
        SHA.upper(),
        f" {SHA}",
        f"{SHA}\n",
        "v1.2.0",
        "g" * 40,
        "unknown",
    ],
)
def test_a_version_must_be_a_full_lowercase_commit_sha(monkeypatch, variable, value) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError, match="40-character lowercase Git commit SHA") as e:
        settings()
    assert value.strip() not in str(e.value)  # errors never echo values


def test_a_production_version_must_be_a_sha_too(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("APP_VERSION", "main")
    with pytest.raises(ValidationError):
        settings()
    monkeypatch.setenv("APP_VERSION", SHA)
    assert settings().version == SHA


# --- Telemetry metadata (for the observability work that follows) --------------------------


def test_resource_attributes_name_the_environment_and_the_exact_version() -> None:
    config = settings(app_env="production", database_url=PG_URL, app_version=SHA)
    assert config.resource_attributes() == {
        "service.name": "spendwise",
        "deployment.environment": "production",
        "service.version": SHA,
    }


def test_resource_attributes_leave_out_an_unknown_version() -> None:
    config = settings(app_env="development", database_url=PG_URL)
    assert config.resource_attributes() == {
        "service.name": "spendwise",
        "deployment.environment": "development",
    }


def test_resource_attributes_hold_nothing_about_the_database() -> None:
    config = settings(app_env="production", database_url=PG_URL, app_version=SHA)
    text = repr(config.resource_attributes())
    assert "not-a-real-password" not in text and "db.example" not in text
