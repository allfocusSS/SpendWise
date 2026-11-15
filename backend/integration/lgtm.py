"""Grafana's LGTM stack (compose.dashboard.yaml) for the dashboard and alert smoke tests.

- `serve()` is their session `stack` fixture: the real Compose stack plus LGTM and the alert
  receiver, with the same isolation as the integration tests (integration/stack.py): its own
  project, ports and image tag, a scrubbed environment, and everything removed afterwards.
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
) -> Iterator[Stack]:
    env = os.environ
    stack = Stack(
        project=env.get(f"{prefix}_PROJECT", project),
        port=int(env.get(f"{prefix}_PORT", str(port))),
        image=env.get(f"{prefix}_IMAGE", image),
        keep=env.get(f"{prefix}_KEEP") == "1",
        compose_files=DASHBOARD_FILES,
        extra_env={"GRAFANA_PORT": env.get(f"{prefix}_GRAFANA_PORT", str(grafana_port))},
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
