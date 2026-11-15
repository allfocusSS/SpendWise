"""GET /api/meta: the environment and exact commit of a deployment, and nothing else."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings

SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
DB_PASSWORD = "not-a-real-password"
PG_URL = f"postgresql+psycopg://spendwise:{DB_PASSWORD}@internal-db.example:5432/spendwise"
API_KEY = "sk-ant-not-a-real-key"


def meta_of(app: FastAPI, **values) -> dict:
    """GET /api/meta with these settings in place of the test suite's."""
    config = Settings(_env_file=None, **values)
    app.dependency_overrides[get_settings] = lambda: config
    response = TestClient(app).get("/api/meta")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_the_test_suite_reports_test_and_no_version(anon_client: TestClient) -> None:
    response = anon_client.get("/api/meta")
    assert response.status_code == 200
    assert response.json() == {"environment": "test", "version": None}


def test_development_reports_its_environment_and_render_commit(app: FastAPI) -> None:
    meta = meta_of(app, app_env="development", database_url=PG_URL, render_git_commit=SHA)
    assert meta == {"environment": "development", "version": SHA}


def test_production_reports_its_environment_and_deployed_commit(app: FastAPI) -> None:
    meta = meta_of(app, app_env="production", database_url=PG_URL, app_version=SHA)
    assert meta == {"environment": "production", "version": SHA}


def test_production_without_a_version_says_so(app: FastAPI) -> None:
    # A deploy that bypassed the deploy wrapper: the version is unknown, never guessed.
    meta = meta_of(app, app_env="production", database_url=PG_URL)
    assert meta == {"environment": "production", "version": None}


def test_no_sign_in_is_needed(anon_client: TestClient) -> None:
    assert anon_client.get("/api/meta").status_code == 200


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_meta_is_read_only(anon_client: TestClient, method: str) -> None:
    assert getattr(anon_client, method)("/api/meta").status_code == 405


def test_nothing_sensitive_is_exposed(app: FastAPI) -> None:
    meta = meta_of(
        app,
        app_env="production",
        database_url=PG_URL,
        app_version=SHA,
        ai_provider="anthropic",
        anthropic_api_key=API_KEY,
    )
    # Exactly two fields: no hostnames, database details, infrastructure IDs, keys or settings.
    assert set(meta) == {"environment", "version"}
    text = str(meta)
    for secret in (DB_PASSWORD, "internal-db.example", "spendwise:", API_KEY, "anthropic"):
        assert secret not in text


def test_meta_is_documented_in_the_openapi_spec(anon_client: TestClient) -> None:
    spec = anon_client.get("/openapi.json").json()
    assert set(spec["paths"]["/api/meta"]) == {"get"}
    schema = spec["components"]["schemas"]["MetaResponse"]
    assert set(schema["properties"]) == {"environment", "version"}
    assert schema["properties"]["environment"]["enum"] == [
        "local",
        "test",
        "development",
        "production",
    ]
