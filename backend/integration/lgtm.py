"""Grafana's LGTM stack (compose.dashboard.yaml) for the dashboard and alert smoke tests.

- `serve()` is their session `stack` fixture: the real Compose stack plus LGTM and the alert
  receiver, with the same isolation as the integration tests (integration/stack.py): its own
  project, ports and image tag, a scrubbed environment, and everything removed afterwards.
- `wait_until_ready()` waits for Grafana, its provisioned data sources and the data source proxy
  routes the tests use (see there).
- `Backends` reaches Prometheus, Loki and Tempo through Grafana's data source proxy: Grafana is
  the only port the stack publishes. It rides out Grafana's brief "plugin not found" answers (see
  `PROXY_UNAVAILABLE`).
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

# The routes through Grafana's data source proxy that the tests use, one per data source. Both the
# readiness check and `Backends` build their requests from these, so they can't drift apart.
PROMETHEUS = "/api/datasources/proxy/uid/prometheus/api/v1/"
LOKI = "/api/datasources/proxy/uid/loki/loki/api/v1/"
TEMPO = "/api/datasources/proxy/uid/tempo/api/"
# The cheapest read-only request on each route that a healthy backend answers with 200.
PROXY_CHECKS = {
    "prometheus": (PROMETHEUS + "query", {"query": "vector(1)"}),
    "loki": (LOKI + "labels", {}),
    "tempo": (TEMPO + "echo", {}),
}

# Grafana's own 404s on the proxy route (a JSON {"message": ...}, unlike the backend's), seen in
# CI and reproduced against the pinned LGTM image. The data source record exists and
# /api/datasources/uid/<uid> answers 200, yet for about 100 ms the proxy answers 404 "Unable to
# find datasource plugin". Cause: after startup Grafana's background plugin installer replaces its
# bundled plugins (Prometheus, Loki and Tempo among them) with newer versions from grafana.com, one
# at a time, over the next several minutes, and a plugin is unregistered between the swap and
# its re-registration. The log reads "Installed plugin update pluginId=tempo", the proxy 404s,
# then "Plugin registered pluginId=tempo". compose.dashboard.yaml turns that installer off
# (GF_PLUGINS_PREINSTALL_DISABLED). A one-off check at startup couldn't catch it anyway, so
# `Backends` also retries exactly these answers, for a bounded time, in case a Grafana swaps
# plugins regardless. Any other answer, 404s from Prometheus, Loki or Tempo included, is the
# real one.
PROXY_UNAVAILABLE = {"Unable to find datasource plugin", "Data source not found"}
PROXY_RETRY = 15  # seconds a proxy request may keep getting one of them before it fails


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
    """Grafana's database, then each provisioned data source and its proxy route, in one deadline.

    /api/health alone isn't enough: Grafana 13 starts its HTTP server and its provisioning as
    concurrent services, so it can answer "database ok" before the provisioned data sources
    exist, and the data source proxy then answers 404. LGTM's own health check (and so
    `docker compose up --wait`) only waits for /api/health.

    Nor is the data source record enough, so each one is followed by a request on the proxy route
    the tests use (`PROXY_CHECKS`): what is waited for is what is used. A proxy that keeps
    answering 404 until the deadline is a failure, with Grafana's answer in the message.
    """
    end = clock() + deadline
    checks: list[tuple[str, str, dict, Callable[[httpx.Response], str | None], str]] = [
        ("Grafana", "/api/health", {}, healthy, "Is Grafana running, and is its database up?")
    ]
    for uid, kind in data_sources.items():
        checks.append(
            (
                f"data source {uid!r}",
                f"/api/datasources/uid/{uid}",
                {},
                provisioned(uid, kind),
                "Is it provisioned (LGTM's grafana-datasources.yaml), under this UID?",
            )
        )
        if uid in PROXY_CHECKS:
            path, params = PROXY_CHECKS[uid]
            checks.append(
                (
                    f"data source {uid!r} proxy",
                    path,
                    params,
                    lambda response: None,  # 200 is the answer
                    "The data source exists, but Grafana can't serve queries through it: is its "
                    "plugin loaded, and does its backend answer?",
                )
            )
    for what, path, params, accept, hint in checks:
        while True:
            try:
                response = grafana.get(path, params=params)
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
                    f"{what} not ready after {deadline}s: GET {path} last answered {last}. {hint}"
                )
            sleep(interval)


def healthy(response: httpx.Response) -> str | None:
    """None once Grafana's database is up; otherwise why it is still starting."""
    database = response.json().get("database")
    return None if database == "ok" else f"200, database {database!r}"


def grafana_message(response: httpx.Response) -> str | None:
    """The `message` of Grafana's own 404, or None (another status, or not Grafana's JSON)."""
    if response.status_code != 404:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    message = body.get("message") if isinstance(body, dict) else None
    return message if isinstance(message, str) else None


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

    def __init__(
        self,
        grafana: httpx.Client,
        retry: float = PROXY_RETRY,
        interval: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.grafana = grafana
        self.retry, self.interval, self.clock, self.sleep = retry, interval, clock, sleep

    def get(self, path: str, params: dict) -> httpx.Response:
        """GET through the proxy, riding out Grafana's brief `PROXY_UNAVAILABLE` answers.

        Only those: any other answer is returned as it is, and one of them lasting longer than
        `retry` seconds raises NotReady with Grafana's own words, so a data source that is really
        missing still fails the test, after `retry` seconds, with a clear message and no bare 404.
        """
        end = self.clock() + self.retry
        while True:
            response = self.grafana.get(path, params=params)
            message = grafana_message(response)
            if message not in PROXY_UNAVAILABLE:
                return response
            if self.clock() > end:
                raise NotReady(
                    f"Grafana's data source proxy kept answering 404 {message!r} for "
                    f"{self.retry}s: GET {path}. The data source record exists, but Grafana "
                    "can't find its plugin: did Grafana restart, or the data source go away?"
                )
            self.sleep(self.interval)

    def prometheus(self, path: str, **params) -> dict:
        response = self.get(PROMETHEUS + path, params)
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
        response = self.get(
            LOKI + "query_range",
            {"query": query, "start": now - 3600 * 10**9, "end": now, "limit": 100},
        )
        response.raise_for_status()
        return response.json()["data"]["result"]

    def tempo(self, path: str, **params) -> httpx.Response:
        return self.get(TEMPO + path, params)
