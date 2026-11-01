"""The stack itself: services healthy, start order, the built frontend, health and docs routes."""

import re

import httpx
import pytest

from integration.stack import Stack


def test_postgres_and_app_are_running_and_healthy(stack: Stack) -> None:
    services = stack.services()

    assert set(services) == {"db", "app"}
    for name, service in services.items():
        assert service["State"] == "running", (name, service)
        assert service["Health"] == "healthy", (name, service)


def test_app_started_only_after_postgres_was_healthy(stack: Stack) -> None:
    # depends_on: condition: service_healthy. Timestamps were recorded right after startup.
    assert stack.db_first_healthy is not None, "pg_isready never passed"
    assert stack.app_started is not None
    assert stack.app_started > stack.db_first_healthy
    assert stack.inspect("app")["Config"]["Image"] == stack.image


def test_postgres_is_not_published_and_app_only_on_loopback(stack: Stack) -> None:
    services = stack.services()

    assert [p for p in services["db"]["Publishers"] if p.get("PublishedPort")] == []
    published = [p for p in services["app"]["Publishers"] if p.get("PublishedPort")]
    assert {(p["URL"], p["PublishedPort"], p["TargetPort"]) for p in published} == {
        ("127.0.0.1", stack.port, 8000)
    }


def test_app_uses_postgresql(stack: Stack) -> None:
    env = dict(item.split("=", 1) for item in stack.inspect("app")["Config"]["Env"])

    assert env["ENVIRONMENT"] == "production"
    assert env["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert env["DATABASE_URL"].endswith("@db:5432/spendwise")


@pytest.mark.parametrize("path", ["/api/health", "/api/health/ready"])
def test_health_endpoints(http, path: str) -> None:
    response = http().get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_docs_and_spec(http) -> None:
    client = http()

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()

    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    assert {"/api/auth/login", "/api/transactions", "/api/analytics/summary"} <= set(
        spec.json()["paths"]
    )


@pytest.mark.parametrize(
    "path", ["/", "/transactions", "/categories", "/analytics", "/login", "/register"]
)
def test_frontend_routes_serve_the_built_app(http, path: str) -> None:
    response = http().get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in response.text
    assert "/src/main.tsx" not in response.text  # the production build, not the Vite dev page


def test_built_bundles_are_served(http) -> None:
    client = http()
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', client.get("/").text)
    assert any(a.endswith(".js") for a in assets) and any(a.endswith(".css") for a in assets)

    for asset in assets:
        response = client.get(asset)
        assert response.status_code == 200, asset
        expected = "javascript" if asset.endswith(".js") else "css"
        assert expected in response.headers["content-type"], asset

    assert client.get("/assets/does-not-exist.js").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/auth/me"),
        ("GET", "/api/categories"),
        ("POST", "/api/categories"),
        ("GET", "/api/transactions"),
        ("POST", "/api/transactions"),
        ("GET", "/api/transactions/1"),
        ("PUT", "/api/transactions/1"),
        ("DELETE", "/api/transactions/1"),
        ("GET", "/api/analytics/summary"),
        ("GET", "/api/analytics/by-category"),
        ("GET", "/api/analytics/monthly-trend"),
    ],
)
def test_data_routes_need_a_session(http, method: str, path: str) -> None:
    response = http().request(method, path, json={} if method in {"POST", "PUT"} else None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_unknown_api_paths_are_json_404s(http) -> None:
    response = http().get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_stack_answers_on_loopback_only(stack: Stack) -> None:
    # Sanity check of the published address the other tests rely on.
    assert httpx.get(f"{stack.base_url}/api/health", timeout=10).status_code == 200
