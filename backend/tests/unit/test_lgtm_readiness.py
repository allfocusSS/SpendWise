"""Waiting for Grafana's provisioned data sources (integration/lgtm.py, `wait_until_ready`).

The race it covers, as seen in CI: Grafana 13 answers /api/health ("database ok") before its
provisioning has created the data sources, so the first Prometheus proxy query got a 404. A fake
Grafana (httpx.MockTransport) answers from a script here, and a fake clock replaces sleeping.
"""

import httpx
import pytest

from integration.lgtm import DATA_SOURCES, NotReady, wait_until_ready

HEALTHY = {"database": "ok", "version": "13.3.0"}
MISSING = {"message": "Data source not found"}


def data_source(uid: str, kind: str | None = None) -> dict:
    return {"uid": uid, "type": kind or DATA_SOURCES[uid], "name": uid.title()}


class FakeGrafana:
    """Answers each path from its script, one entry per request; the last entry repeats."""

    def __init__(self, script: dict[str, list]) -> None:
        self.script = script
        self.requests: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        answers = self.script[path]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.sleeps += 1


def ready(**overrides: list) -> dict[str, list]:
    """Grafana with every data source there, except what `overrides` scripts (by UID)."""
    script = {"/api/health": [(200, HEALTHY)]}
    for uid in DATA_SOURCES:
        script[f"/api/datasources/uid/{uid}"] = overrides.get(uid, [(200, data_source(uid))])
    return script


def run(script: dict[str, list], deadline: float = 120) -> tuple[FakeGrafana, Clock]:
    grafana, clock = FakeGrafana(script), Clock()
    with httpx.Client(
        base_url="http://grafana.test", transport=httpx.MockTransport(grafana.handle)
    ) as client:
        wait_until_ready(client, deadline=deadline, clock=clock, sleep=clock.sleep)
    return grafana, clock


def test_health_ok_then_the_data_source_appears() -> None:
    # The CI race: Grafana is healthy, Prometheus isn't provisioned yet, then it is.
    grafana, clock = run(
        ready(prometheus=[(404, MISSING), (404, MISSING), (200, data_source("prometheus"))])
    )
    assert grafana.requests == [
        "/api/health",
        "/api/datasources/uid/prometheus",
        "/api/datasources/uid/prometheus",
        "/api/datasources/uid/prometheus",
        "/api/datasources/uid/loki",
        "/api/datasources/uid/tempo",
    ]
    assert clock.sleeps == 2
    # It only looks the data sources up: no proxy query before they exist.
    assert not any("/proxy/" in path for path in grafana.requests)


def test_grafana_still_starting_is_waited_for() -> None:
    script = ready()
    script["/api/health"] = [
        httpx.ConnectError("refused"),
        (503, {"database": "failing"}),
        (200, {"database": "migrating"}),
        (200, HEALTHY),
    ]
    script["/api/datasources/uid/loki"] = [(502, {}), (200, data_source("loki"))]
    grafana, clock = run(script)
    assert grafana.requests.count("/api/health") == 4
    assert grafana.requests.count("/api/datasources/uid/loki") == 2
    assert clock.sleeps == 4


def test_a_data_source_that_never_appears_fails_at_the_deadline() -> None:
    with pytest.raises(NotReady) as raised:
        run(ready(tempo=[(404, MISSING)]), deadline=10)
    message = str(raised.value)
    assert "data source 'tempo' not ready after 10s" in message
    assert "GET /api/datasources/uid/tempo last answered 404" in message
    assert "Data source not found" in message
    assert "grafana-datasources.yaml" in message


@pytest.mark.parametrize("status", [400, 401, 403, 405, 500])
def test_any_other_answer_fails_at_once(status: int) -> None:
    grafana = FakeGrafana(ready(prometheus=[(status, {"message": "nope"})]))
    clock = Clock()
    with (
        httpx.Client(base_url="http://g.test", transport=httpx.MockTransport(grafana.handle)) as c,
        pytest.raises(NotReady, match=rf"data source 'prometheus': .* answered {status} "),
    ):
        wait_until_ready(c, clock=clock, sleep=clock.sleep)
    assert grafana.requests.count("/api/datasources/uid/prometheus") == 1  # not retried
    assert clock.sleeps == 0


def test_a_data_source_of_the_wrong_type_fails_at_once() -> None:
    with pytest.raises(NotReady, match=r"'loki': expected type 'loki', .* type 'prometheus'"):
        run(ready(loki=[(200, data_source("loki", kind="prometheus"))]))


def test_the_deadline_covers_every_check_together() -> None:
    # 5 s for Grafana, then 6 s for Prometheus: each under 10 s, together over it. Each
    # check waits within what is left of the one deadline, not a fresh one.
    script = ready(prometheus=[(404, MISSING)] * 12 + [(200, data_source("prometheus"))])
    script["/api/health"] = [(503, {})] * 10 + [(200, HEALTHY)]
    with pytest.raises(NotReady, match="data source 'prometheus' not ready after 10s"):
        run(script, deadline=10)


def test_the_tests_wait_for_the_data_sources_they_query() -> None:
    assert DATA_SOURCES == {"prometheus": "prometheus", "loki": "loki", "tempo": "tempo"}
