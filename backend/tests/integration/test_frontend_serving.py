"""Serving the built frontend from FastAPI (production image, FRONTEND_DIST set)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.frontend import mount_frontend
from app.main import create_app

INDEX = "<!doctype html><title>SpendWise</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A minimal Vite build: index.html, a root file and one hashed bundle."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "favicon.svg").write_text("<svg/>")
    (root / "assets" / "index-abc123.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("outside dist")
    return root


@pytest.fixture
def spa(client: TestClient, dist: Path) -> TestClient:
    mount_frontend(client.app, dist)
    return client


@pytest.mark.parametrize("path", ["/", "/transactions", "/categories", "/analytics", "/a/b?x=1"])
def test_client_routes_get_index_html(spa: TestClient, path: str) -> None:
    # A direct load or refresh of any client-side route returns the app shell.
    response = spa.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert spa.head(path).status_code == 200


def test_root_files_and_bundles_are_served(spa: TestClient) -> None:
    assert spa.get("/favicon.svg").text == "<svg/>"

    bundle = spa.get("/assets/index-abc123.js")
    assert bundle.status_code == 200
    assert bundle.text == "console.log('app')"
    assert "javascript" in bundle.headers["content-type"]


def test_missing_bundle_is_404_not_index_html(spa: TestClient) -> None:
    assert spa.get("/assets/index-old999.js").status_code == 404


def test_api_still_works(spa: TestClient) -> None:
    assert spa.get("/api/health").json() == {"status": "ok"}
    assert len(spa.get("/api/categories").json()) > 0


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/unknown", "/api/transactions/x/y"])
def test_unknown_api_paths_stay_json_404(spa: TestClient, path: str) -> None:
    for method in ("GET", "POST", "DELETE"):
        response = spa.request(method, path)
        assert response.status_code == 404, (method, path)
        assert response.json() == {"detail": "Not Found"}


def test_wrong_method_on_api_route_is_still_405(spa: TestClient) -> None:
    assert spa.put("/api/health").status_code == 405


def test_docs_are_not_replaced_by_the_app(spa: TestClient) -> None:
    assert "swagger" in spa.get("/docs").text.lower()
    assert "/api/health" in spa.get("/openapi.json").json()["paths"]


def test_openapi_schema_is_unchanged(spa: TestClient) -> None:
    assert spa.get("/openapi.json").json() == create_app().openapi()


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"])
def test_files_outside_dist_are_not_served(spa: TestClient, path: str) -> None:
    response = spa.get(path)

    assert "outside dist" not in response.text


def test_missing_build_fails_at_startup(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no index.html"):
        mount_frontend(create_app(), tmp_path)


def test_frontend_is_not_served_without_frontend_dist(client: TestClient) -> None:
    # Local development: Vite serves the frontend; the backend only answers /api and /docs.
    assert client.get("/transactions").status_code == 404
