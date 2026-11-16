"""Grafana's LGTM stack (compose.dashboard.yaml) for the dashboard and alert smoke tests.

- `serve()` is their session `stack` fixture: the real Compose stack plus LGTM and the alert
  receiver, with the same isolation as the integration tests (integration/stack.py): its own
  project, ports and image tag, a scrubbed environment, and everything removed afterwards.
- `wait_until_ready()` waits for Grafana and its provisioned data sources (see there).
- `Backends` reaches Prometheus, Loki and Tempo through Grafana's data source proxy: Grafana is
  the only port the stack publishes.
- `wait_for()` polls a check until it passes or a deadline expires: no fixed sleeps.

Settings, for a suite whose prefix is e.g. SPENDWISE_DASHBOARD (all optional): `<prefix>_PROJECT`,
`<prefix>_PORT` (the app), `<prefix>_GRAFANA_PORT`, `<prefix>_IMAGE`, `<prefix>_KEEP=1` to leave
the stack running, and `<prefix>_LOG_FILE` to write the run's container logs there (CI uploads it).
"""

import contextlib
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from integration.stack import DASHBOARD_FILES, Stack, StackError


def serve(
    request: pytest.FixtureRequest,
    prefix: str,
    *,
    project: str,
    port: int,
    grafana_port: int,
    image: str,
    compose_files: tuple[Path, ...] = DASHBOARD_FILES,
    extra_env: dict[str, str] | None = None,
) -> Iterator[Stack]:
    env = os.environ
    stack = Stack(
        project=env.get(f"{prefix}_PROJECT", project),
        port=int(env.get(f"{prefix}_PORT", str(port))),
        image=env.get(f"{prefix}_IMAGE", image),
        keep=env.get(f"{prefix}_KEEP") == "1",
        compose_files=compose_files,
        extra_env={
            "GRAFANA_PORT": env.get(f"{prefix}_GRAFANA_PORT", str(grafana_port)),
            **(extra_env or {}),
        },
    )
    try:
        stack.check_prerequisites()
        stack.down(volumes=True)  # leftovers from an interrupted earlier run
        stack.up(build=True)  # waits for the app, LGTM's own health check and the receiver
    except Exception as error:
        logs = stack.logs()
        if not stack.keep:
            with contextlib.suppress(StackError):
                stack.down(volumes=True)
        pytest.exit(f"The stack did not start:\n{error}\n--- logs ---\n{logs}", returncode=1)

    yield stack

    log_file = env.get(f"{prefix}_LOG_FILE")
    if log_file:
        Path(log_file).write_text(stack.logs(tail=3000))
    if request.session.testsfailed:
        capture = request.config.pluginmanager.get_plugin("capturemanager")
        with capture.global_and_fixture_disabled():
            print(f"\n--- docker compose logs ({stack.project}) ---\n{stack.logs(tail=300)}")
    if not stack.keep:
        stack.down(volumes=True)


@contextlib.contextmanager
def grafana_client(stack: Stack) -> Iterator[httpx.Client]:
    """Grafana's HTTP API (anonymous, read-only), the only port the stack publishes."""
    port = stack.extra_env["GRAFANA_PORT"]
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
        yield client


DEADLINE = 120

# The data sources LGTM provisions (its grafana-datasources.yaml) and the tests use: UID → type.
DATA_SOURCES = {"prometheus": "prometheus", "loki": "loki", "tempo": "tempo"}
# Answers that mean "still starting", retried until the deadline: the data source isn't
# provisioned yet (404), or something in front of it isn't up yet (502, 503). Any other answer
# is a real error (a wrong UID or type, a permission, a URL) and fails at once.
STARTING = {404, 502, 503}


class NotReady(RuntimeError):
    """Grafana or one of its data sources isn't usable: what, where, and the last answer."""


def wait_until_ready(
    grafana: httpx.Client,
    data_sources: dict[str, str] = DATA_SOURCES,
    deadline: float = DEADLINE,
    interval: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Grafana's database, then each provisioned data source, all within one deadline.

    /api/health alone isn't enough: Grafana 13 starts its HTTP server and its provisioning as
    concurrent services, so it can answer "database ok" before the provisioned data sources
    exist, and the data source proxy then answers 404. LGTM's own health check (and so
    `docker compose up --wait`) only waits for /api/health.
    """
    end = clock() + deadline
    checks = [("Grafana", "/api/health", healthy)] + [
        (f"data source {uid!r}", f"/api/datasources/uid/{uid}", provisioned(uid, kind))
        for uid, kind in data_sources.items()
    ]
    for what, path, accept in checks:
        while True:
            try:
                response = grafana.get(path)
            except httpx.TransportError as error:  # not listening yet
                last = f"no answer ({type(error).__name__})"
            else:
                body = response.text[:200]
                if response.status_code == 200:
                    still_starting = accept(response)
                    if still_starting is None:
                        break
                    last = still_starting
                elif response.status_code in STARTING:
                    last = f"{response.status_code} {body}"
                else:
                    raise NotReady(
                        f"{what}: GET {path} answered {response.status_code} {body} "
                        "(not a startup answer: check the UID, the permissions and the URL)"
                    )
            if clock() > end:
                raise NotReady(
                    f"{what} not ready after {deadline}s: GET {path} last answered {last}. "
                    "Is it provisioned (LGTM's grafana-datasources.yaml), under this UID?"
                )
            sleep(interval)


def healthy(response: httpx.Response) -> str | None:
    """None once Grafana's database is up; otherwise why it is still starting."""
    database = response.json().get("database")
    return None if database == "ok" else f"200, database {database!r}"


def provisioned(uid: str, kind: str) -> Callable[[httpx.Response], str | None]:
    def accept(response: httpx.Response) -> None:
        found = response.json()
        if (found.get("uid"), found.get("type")) != (uid, kind):
            raise NotReady(
                f"data source {uid!r}: expected type {kind!r}, Grafana has "
                f"uid {found.get('uid')!r} of type {found.get('type')!r}"
            )

    return accept


def wait_for(what: str, check: Callable[[], object], deadline: float = DEADLINE):
    end = time.monotonic() + deadline
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > end:
            pytest.fail(f"Timed out after {deadline}s waiting for {what}")
        time.sleep(1)


class Backends:
    """Prometheus, Loki and Tempo, through Grafana's data source proxy."""

    def __init__(self, grafana: httpx.Client) -> None:
        self.grafana = grafana

    def prometheus(self, path: str, **params) -> dict:
        response = self.grafana.get(
            f"/api/datasources/proxy/uid/prometheus/api/v1/{path}", params=params
        )
        response.raise_for_status()
        return response.json()

    def query(self, expr: str) -> list[dict]:
        result = self.prometheus("query", query=expr)
        assert result["status"] == "success", (expr, result)
        return result["data"]["result"]

    def value(self, expr: str) -> float | None:
        result = self.query(expr)
        return float(result[0]["value"][1]) if result else None

    def loki(self, query: str) -> list[dict]:
        now = time.time_ns()
        response = self.grafana.get(
            "/api/datasources/proxy/uid/loki/loki/api/v1/query_range",
            params={"query": query, "start": now - 3600 * 10**9, "end": now, "limit": 100},
        )
        response.raise_for_status()
        return response.json()["data"]["result"]

    def tempo(self, path: str, **params) -> httpx.Response:
        return self.grafana.get(f"/api/datasources/proxy/uid/tempo/api/{path}", params=params)
