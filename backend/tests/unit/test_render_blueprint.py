"""The Render Blueprint (render.yaml): Render is DEVELOPMENT (docs/environments.md).

It deploys main by itself once CI passed, says it is development, keeps its own database, and
stays on free plans. Read as data; nothing talks to Render.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT = ROOT / "render.yaml"


@pytest.fixture(scope="module")
def blueprint() -> dict[str, Any]:
    return yaml.safe_load(BLUEPRINT.read_text())


@pytest.fixture(scope="module")
def service(blueprint) -> dict[str, Any]:
    (service,) = blueprint["services"]
    return service


def env_vars(service: dict[str, Any]) -> dict[str, Any]:
    return {v["key"]: v.get("value", v.get("fromDatabase")) for v in service["envVars"]}


def test_render_is_development(service) -> None:
    assert env_vars(service)["APP_ENV"] == "development"
    # Nothing on Render claims to be production; the old variable is gone from the Blueprint.
    assert "ENVIRONMENT" not in env_vars(service)
    assert "production" not in {str(v) for v in env_vars(service).values()}


def test_development_deploys_main_only_after_ci_passed(service) -> None:
    assert service["branch"] == "main"
    assert service["autoDeployTrigger"] == "checksPass"
    assert "autoDeploy" not in service  # the older setting would compete with the trigger
    assert service["healthCheckPath"] == "/api/health/ready"


def test_the_version_is_left_to_render(service) -> None:
    # RENDER_GIT_COMMIT, set by Render for every deploy, is the version (app/core/config.py). A
    # fixed APP_VERSION here would be wrong after the next commit.
    assert "APP_VERSION" not in env_vars(service)
    assert "RENDER_GIT_COMMIT" not in env_vars(service)


def test_development_keeps_its_own_render_database(blueprint, service) -> None:
    assert env_vars(service)["DATABASE_URL"] == {
        "name": "spendwise-db",
        "property": "connectionString",
    }
    (database,) = blueprint["databases"]
    assert database["name"] == "spendwise-db"
    assert database["databaseName"] == "spendwise"
    # Not reachable from outside Render, so from production neither.
    assert database["ipAllowList"] == []
    assert database["region"] == service["region"]


def test_the_existing_service_and_database_keep_their_names(blueprint, service) -> None:
    # Render matches Blueprint resources by name: a new name would create another service (a new
    # URL instead of https://spendwise-amyx.onrender.com) or another, empty database.
    assert service["name"] == "spendwise"
    assert [d["name"] for d in blueprint["databases"]] == ["spendwise-db"]


def test_free_plans_only(blueprint, service) -> None:
    assert service["plan"] == "free"
    assert all(d["plan"] == "free" for d in blueprint["databases"])
    for paid in ("numInstances", "scaling", "disk", "previews"):
        assert paid not in service
    assert len(blueprint["services"]) == 1 and len(blueprint["databases"]) == 1


def test_no_secrets_in_the_blueprint(service) -> None:
    # The database URL (with its generated password) comes from Render, never from this file.
    for var in service["envVars"]:
        value = str(var.get("value", ""))
        assert not value.startswith(("postgres://", "postgresql://")), var["key"]
        assert "password" not in var["key"].lower() and "secret" not in var["key"].lower()
