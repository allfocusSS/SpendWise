"""Integration tests against the real Docker Compose stack: built frontend, FastAPI, PostgreSQL.

Run from the repo root with `make integration` (or `cd backend && uv run pytest integration`).
Nothing is mocked or bypassed: every request is real HTTP to the running app, signed in through
the real auth endpoints, stored in the real PostgreSQL container.

The stack is started once per test session and removed afterwards, volume included (see
integration/stack.py for the settings and how it is kept apart from your local stack).
"""

import contextlib
import os
import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from integration.stack import Stack, StackError

RESTARTS_STACK = "restarts_stack"
COOKIE_NAME = "spendwise_session"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", f"{RESTARTS_STACK}: stops and restarts the stack; always runs last"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Restarting the stack drops every open connection, so those tests go after all others.
    items.sort(key=lambda item: item.get_closest_marker(RESTARTS_STACK) is not None)


LOG_LINES = 1000  # per container; the full suite writes a few hundred access-log lines


def show(request: pytest.FixtureRequest, text: str) -> None:
    """Print past pytest's output capture (prints from session teardown are otherwise lost)."""
    capture = request.config.pluginmanager.get_plugin("capturemanager")
    with capture.global_and_fixture_disabled():
        print(text)


@pytest.fixture(scope="session")
def stack(request: pytest.FixtureRequest) -> Iterator[Stack]:
    stack = Stack.from_env()
    try:
        stack.check_prerequisites()
        stack.down(volumes=True)  # leftovers from an interrupted earlier run
        stack.up(build=True)
        stack.record_startup()
    except Exception as error:  # any failure: report it once, with logs, and leave nothing behind
        logs = stack.logs()
        if not stack.keep:
            with contextlib.suppress(StackError):  # e.g. Docker itself is missing
                stack.down(volumes=True)
        pytest.exit(
            f"The Compose stack did not start:\n{error}\n--- logs ---\n{logs}", returncode=1
        )

    yield stack

    log_file = os.environ.get("SPENDWISE_IT_LOG_FILE")
    if request.session.testsfailed or log_file:
        logs = stack.logs(tail=LOG_LINES)
        if log_file:  # e.g. uploaded by CI when the job fails
            Path(log_file).write_text(logs)
        if request.session.testsfailed:
            show(request, f"\n--- docker compose logs ({stack.project}) ---\n{logs}")
    if stack.keep:
        show(request, f"SPENDWISE_IT_KEEP=1: stack '{stack.project}' left at {stack.base_url}")
    else:
        stack.down(volumes=True)


@dataclass
class User:
    """One signed-in person: their own HTTP client (and so their own session cookie)."""

    email: str
    password: str
    client: httpx.Client

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.client.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.client.post(url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        return self.client.put(url, **kwargs)

    def patch(self, url: str, **kwargs) -> httpx.Response:
        return self.client.patch(url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        return self.client.delete(url, **kwargs)

    def category_ids(self) -> dict[str, int]:
        response = self.get("/api/categories")
        assert response.status_code == 200, response.text
        return {c["name"]: c["id"] for c in response.json()}


def unique_email(label: str) -> str:
    """A new address per call, so runs never collide (even against a kept stack)."""
    return f"it-{label}-{secrets.token_hex(6)}@example.com"


@pytest.fixture
def http(stack: Stack) -> Iterator[Callable[[], httpx.Client]]:
    """Factory for fresh, signed-out HTTP clients pointed at the stack."""
    clients: list[httpx.Client] = []

    def make(**kwargs) -> httpx.Client:
        client = httpx.Client(base_url=stack.base_url, timeout=30, **kwargs)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


@pytest.fixture
def new_user(http) -> Callable[[str], User]:
    """Factory: sign up a new user through POST /api/auth/signup and return them signed in."""

    def make(label: str = "user") -> User:
        email, password = unique_email(label), secrets.token_urlsafe(18)
        client = http()
        response = client.post("/api/auth/signup", json={"email": email, "password": password})
        assert response.status_code == 201, response.text
        return User(email=email, password=password, client=client)

    return make


@pytest.fixture
def alice(new_user) -> User:
    return new_user("alice")


@pytest.fixture
def bob(new_user) -> User:
    return new_user("bob")
