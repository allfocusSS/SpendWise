"""Waiting for Grafana's data sources and their proxy routes (integration/lgtm.py).

Two races, both seen in CI as a bare 404 from the first Prometheus query through the proxy:

- At startup, Grafana 13 answers /api/health ("database ok") before its provisioning has created
  the data sources: `wait_until_ready` waits for each record.
- After startup, with the record in place and /api/datasources/uid/<uid> answering 200, the proxy
  route itself briefly answers 404 "Unable to find datasource plugin": about 100 ms while Grafana's
  background installer swaps a bundled plugin for a newer one, at any point in the first several
  minutes (reproduced against the pinned LGTM image; see PROXY_UNAVAILABLE in lgtm.py).
  `wait_until_ready` also waits for the proxy route, and `Backends` rides out a later one, for a
  bounded time.

A fake Grafana (httpx.MockTransport) answers from a script here, and a fake clock replaces sleeping.
"""

import httpx
import pytest

from integration.lgtm import (
    DATA_SOURCES,
    LOKI,
    PROMETHEUS,
    PROXY_CHECKS,
    PROXY_RETRY,
    TEMPO,
    Backends,
    NotReady,
    grafana_message,
    wait_until_ready,
)

HEALTHY = {"database": "ok", "version": "13.3.0"}
MISSING = {"message": "Data source not found"}
NO_PLUGIN = {"message": "Unable to find datasource plugin"}
SUCCESS = {"status": "success", "data": {"resultType": "vector", "result": []}}


def data_source(uid: str, kind: str | None = None) -> dict:
    return {"uid": uid, "type": kind or DATA_SOURCES[uid], "name": uid.title()}


def record(uid: str) -> str:
    return f"/api/datasources/uid/{uid}"


def proxy(uid: str) -> str:
    return PROXY_CHECKS[uid][0]


class FakeGrafana:
    """Answers each path from its script, one entry per request; the last entry repeats.

    An answer is (status, body): a dict is sent as JSON, a string as plain text.
    """

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
        if isinstance(body, str):
            return httpx.Response(status, text=body)
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


def ready(proxies: dict[str, list] | None = None, **records: list) -> dict[str, list]:
    """Grafana with every data source and proxy route up, except what is scripted (by UID)."""
    script = {"/api/health": [(200, HEALTHY)]}
    for uid in DATA_SOURCES:
        script[record(uid)] = records.get(uid, [(200, data_source(uid))])
        script[proxy(uid)] = (proxies or {}).get(uid, [(200, SUCCESS)])
    return script


def wait(
    script: dict[str, list], deadline: float = 120
) -> tuple[FakeGrafana, Clock, Exception | None]:
    """Run `wait_until_ready` against the script; the NotReady it raised, if any."""
    grafana, clock = FakeGrafana(script), Clock()
    error = None
    with httpx.Client(
        base_url="http://grafana.test", transport=httpx.MockTransport(grafana.handle)
    ) as client:
        try:
            wait_until_ready(client, deadline=deadline, clock=clock, sleep=clock.sleep)
        except NotReady as raised:
            error = raised
    return grafana, clock, error


def run(script: dict[str, list], deadline: float = 120) -> tuple[FakeGrafana, Clock]:
    grafana, clock, error = wait(script, deadline)
    assert error is None, error
    return grafana, clock


def fails(script: dict[str, list], deadline: float = 120) -> tuple[FakeGrafana, Clock, str]:
    grafana, clock, error = wait(script, deadline)
    assert isinstance(error, NotReady), "wait_until_ready should have raised NotReady"
    return grafana, clock, str(error)


# --- wait_until_ready: the data source records


def test_health_ok_then_the_data_source_appears() -> None:
    # The first CI race: Grafana is healthy, Prometheus isn't provisioned yet, then it is.
    grafana, clock = run(
        ready(prometheus=[(404, MISSING), (404, MISSING), (200, data_source("prometheus"))])
    )
    assert grafana.requests == [
        "/api/health",
        record("prometheus"),
        record("prometheus"),
        record("prometheus"),
        proxy("prometheus"),
        record("loki"),
        proxy("loki"),
        record("tempo"),
        proxy("tempo"),
    ]
    assert clock.sleeps == 2
    # A proxy route is only tried once its own record is there.
    for uid in DATA_SOURCES:
        first_proxy = grafana.requests.index(proxy(uid))
        assert grafana.requests.index(record(uid)) < first_proxy
        assert record(uid) not in grafana.requests[first_proxy:]


def test_grafana_still_starting_is_waited_for() -> None:
    script = ready()
    script["/api/health"] = [
        httpx.ConnectError("refused"),
        (503, {"database": "failing"}),
        (200, {"database": "migrating"}),
        (200, HEALTHY),
    ]
    script[record("loki")] = [(502, {}), (200, data_source("loki"))]
    grafana, clock = run(script)
    assert grafana.requests.count("/api/health") == 4
    assert grafana.requests.count(record("loki")) == 2
    assert clock.sleeps == 4


def test_a_data_source_that_never_appears_fails_at_the_deadline() -> None:
    _, _, message = fails(ready(tempo=[(404, MISSING)]), deadline=10)
    assert "data source 'tempo' not ready after 10s" in message
    assert f"GET {record('tempo')} last answered 404" in message
    assert "Data source not found" in message
    assert "grafana-datasources.yaml" in message


@pytest.mark.parametrize("status", [400, 401, 403, 405, 500])
def test_any_other_answer_fails_at_once(status: int) -> None:
    grafana, clock, message = fails(ready(prometheus=[(status, {"message": "nope"})]))
    assert f"data source 'prometheus': GET {record('prometheus')} answered {status} " in message
    assert grafana.requests.count(record("prometheus")) == 1  # not retried
    assert clock.sleeps == 0


def test_a_data_source_of_the_wrong_type_fails_at_once() -> None:
    _, _, message = fails(ready(loki=[(200, data_source("loki", kind="prometheus"))]))
    assert "'loki': expected type 'loki', " in message
    assert "type 'prometheus'" in message


def test_the_deadline_covers_every_check_together() -> None:
    # 5 s for Grafana, then 6 s for Prometheus: each under 10 s, together over it. Each
    # check waits within what is left of the one deadline, not a fresh one.
    script = ready(prometheus=[(404, MISSING)] * 12 + [(200, data_source("prometheus"))])
    script["/api/health"] = [(503, {})] * 10 + [(200, HEALTHY)]
    _, _, message = fails(script, deadline=10)
    assert "data source 'prometheus' not ready after 10s" in message


def test_the_tests_wait_for_the_data_sources_they_query() -> None:
    assert DATA_SOURCES == {"prometheus": "prometheus", "loki": "loki", "tempo": "tempo"}
    assert set(PROXY_CHECKS) == set(DATA_SOURCES)


# --- wait_until_ready: the proxy routes


def test_a_proxy_that_is_late_after_its_record_is_waited_for() -> None:
    # The record answers 200, the proxy 404 "Unable to find datasource plugin" twice, then 200.
    grafana, clock = run(
        ready(proxies={"prometheus": [(404, NO_PLUGIN), (404, NO_PLUGIN), (200, SUCCESS)]})
    )
    assert grafana.requests.count(proxy("prometheus")) == 3
    assert grafana.requests.count(record("prometheus")) == 1
    assert clock.sleeps == 2
    # The others are checked once the first is through.
    assert grafana.requests[-4:] == [record("loki"), proxy("loki"), record("tempo"), proxy("tempo")]


@pytest.mark.parametrize("status", [502, 503])
def test_a_proxy_whose_backend_is_not_up_yet_is_waited_for(status: int) -> None:
    grafana, clock = run(ready(proxies={"loki": [(status, {"message": "starting"}), (200, {})]}))
    assert grafana.requests.count(proxy("loki")) == 2
    assert clock.sleeps == 1


def test_a_proxy_that_never_serves_fails_at_the_deadline_with_grafanas_answer() -> None:
    # Persistent 404s are a failure, never swallowed: the message says which route, what Grafana
    # answered, and how long it waited.
    grafana, clock, message = fails(ready(proxies={"tempo": [(404, NO_PLUGIN)]}), deadline=10)
    assert "data source 'tempo' proxy not ready after 10s" in message
    assert f"GET {proxy('tempo')} last answered 404" in message
    assert "Unable to find datasource plugin" in message
    assert "plugin" in message.split("last answered")[1]
    assert clock.now >= 10 and clock.now < 11  # bounded: it stopped at the deadline
    assert grafana.requests.count(proxy("tempo")) > 5  # and tried again and again until then


@pytest.mark.parametrize("status", [400, 401, 403, 500])
def test_a_proxy_answering_anything_else_fails_at_once(status: int) -> None:
    grafana, clock, message = fails(ready(proxies={"loki": [(status, {"message": "nope"})]}))
    assert f"data source 'loki' proxy: GET {proxy('loki')} answered {status} " in message
    assert "nope" in message
    assert grafana.requests.count(proxy("loki")) == 1
    assert clock.sleeps == 0


def test_the_record_and_the_proxy_share_one_deadline() -> None:
    # 4 s waiting for the record, then the proxy never comes: it fails at 10 s in all, not 14.
    script = ready(
        prometheus=[(404, MISSING)] * 8 + [(200, data_source("prometheus"))],
        proxies={"prometheus": [(404, NO_PLUGIN)]},
    )
    _, clock, message = fails(script, deadline=10)
    assert "data source 'prometheus' proxy not ready after 10s" in message
    assert 10 <= clock.now < 11


# --- Backends: the proxy answering 404 again after startup


def backends(
    script: dict[str, list], retry: float = PROXY_RETRY
) -> tuple[Backends, FakeGrafana, Clock]:
    grafana, clock = FakeGrafana(script), Clock()
    client = httpx.Client(
        base_url="http://grafana.test", transport=httpx.MockTransport(grafana.handle)
    )
    return Backends(client, retry=retry, clock=clock, sleep=clock.sleep), grafana, clock


def test_backends_use_the_routes_the_readiness_check_waits_for() -> None:
    assert proxy("prometheus") == PROMETHEUS + "query"
    assert proxy("loki").startswith(LOKI)
    assert proxy("tempo").startswith(TEMPO)
    script = {
        PROMETHEUS + "query": [(200, SUCCESS)],
        LOKI + "query_range": [(200, {"data": {"result": []}})],
    }
    client, grafana, _ = backends(script)
    client.query("up")
    client.loki('{a="b"}')
    assert grafana.requests == [proxy("prometheus"), LOKI + "query_range"]


@pytest.mark.parametrize("answer", [NO_PLUGIN, MISSING])
def test_a_proxy_that_blinks_after_startup_is_retried(answer: dict) -> None:
    # The CI failure: a query lands in the fraction of a second the proxy answers 404.
    client, grafana, clock = backends(
        {PROMETHEUS + "query": [(404, answer), (404, answer), (200, SUCCESS)]}
    )
    assert client.query("spendwise_transaction_created_total") == []
    assert grafana.requests.count(PROMETHEUS + "query") == 3
    assert clock.sleeps == 2


def test_every_backend_rides_out_a_blink() -> None:
    loki_body = {"data": {"result": [{"stream": {}, "values": []}]}}
    script = {
        LOKI + "query_range": [(404, NO_PLUGIN), (200, loki_body)],
        TEMPO + "search": [(404, NO_PLUGIN), (404, NO_PLUGIN), (200, {"traces": []})],
    }
    client, grafana, clock = backends(script)
    assert client.loki('{a="b"}') == loki_body["data"]["result"]
    assert client.tempo("search", q="{}").json() == {"traces": []}
    assert grafana.requests.count(LOKI + "query_range") == 2
    assert grafana.requests.count(TEMPO + "search") == 3
    assert clock.sleeps == 3


def test_a_blink_that_never_ends_fails_with_grafanas_words() -> None:
    client, grafana, clock = backends({PROMETHEUS + "query": [(404, NO_PLUGIN)]}, retry=15)
    with pytest.raises(NotReady) as raised:
        client.query("up")
    message = str(raised.value)
    assert "kept answering 404 'Unable to find datasource plugin' for 15s" in message
    assert f"GET {PROMETHEUS}query" in message
    assert 15 <= clock.now < 16  # bounded by the window, not forever
    assert grafana.requests.count(PROMETHEUS + "query") > 10


def test_a_data_source_that_is_really_gone_fails_after_the_window_not_at_once() -> None:
    client, _, clock = backends({LOKI + "query_range": [(404, MISSING)]}, retry=5)
    with pytest.raises(NotReady, match="kept answering 404 'Data source not found' for 5s"):
        client.loki('{a="b"}')
    assert 5 <= clock.now < 6


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, "404 page not found"),  # Prometheus's own
        (404, "trace not found"),  # Tempo's own
        (404, {"message": "something Grafana says about something else"}),
        (404, {"message": 42}),
        (404, ["not", "an", "object"]),
        (400, NO_PLUGIN),  # the message alone isn't enough: only on a 404
        (502, {"message": "Bad Gateway"}),  # the stopped-Prometheus case
        (503, "unavailable"),
    ],
)
def test_every_other_answer_is_returned_as_it_is_at_once(status: int, body) -> None:
    client, grafana, clock = backends({TEMPO + "search": [(status, body)]})
    response = client.tempo("search")
    assert response.status_code == status
    assert grafana.requests == [TEMPO + "search"]  # asked once
    assert clock.sleeps == 0


def test_a_backends_own_error_still_raises_for_status() -> None:
    client, grafana, clock = backends({PROMETHEUS + "query": [(502, {"message": "Bad Gateway"})]})
    with pytest.raises(httpx.HTTPStatusError, match="502"):
        client.query("up")
    assert grafana.requests == [PROMETHEUS + "query"]
    assert clock.sleeps == 0


def test_grafana_message_reads_only_a_grafana_404() -> None:
    def answer(status: int, **kwargs) -> httpx.Response:
        return httpx.Response(status, **kwargs)

    assert grafana_message(answer(404, json=NO_PLUGIN)) == "Unable to find datasource plugin"
    assert grafana_message(answer(404, text="not json")) is None
    assert grafana_message(answer(404, json={"other": 1})) is None
    assert grafana_message(answer(200, json=NO_PLUGIN)) is None
