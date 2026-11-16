"""Evidence collection (oncall_responder/evidence.py): fixed queries, bounds, GET only.

The point of these tests: nothing a model, a log line or an alert says can become a query, a URL
or a trace ID, and nothing the backends return can grow the evidence past its bounds.
"""

import http.client
import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from oncall_responder import evidence as ev
from oncall_responder.incident import CATEGORIES, parse_incident
from oncall_support import (
    AI_SCENARIO,
    GRAFANA,
    INJECTION,
    NOW,
    PATTERN_CANARIES,
    FakeBackends,
    incident_json,
    streams,
    traces,
    vector,
)

TRACE = "3b7702ef0f10599e35f57334f97f3457"
EXPECTED = {
    "common": {"common.version", "traces.errors"},
    "http": {
        "http.request_rate",
        "http.error_ratio",
        "http.errors_by_route",
        "http.p95_latency",
        "http.active_requests",
        "logs.http",
        "traces.slow",
    },
    "transaction": {
        "transaction.saved",
        "transaction.failed_by_type",
        "transaction.system_failure_ratio",
        "logs.transaction",
    },
    "ai": {"ai.requests", "ai.errors_by_type", "ai.failure_ratio", "ai.p95_duration", "logs.ai"},
    "auth": {"auth.refused_per_minute", "auth.login_request_rate", "logs.auth"},
}
METRICS = {
    "target_info",
    "http_server_request_duration_seconds_count",
    "http_server_request_duration_seconds_bucket",
    "http_server_active_requests",
    "spendwise_transaction_created_total",
    "spendwise_transaction_create_error_total",
    "spendwise_ai_parse_request_total",
    "spendwise_ai_parse_error_total",
    "spendwise_ai_parse_duration_seconds_bucket",
    "spendwise_auth_sign_in_failure_total",
}


def incident(category: str = "ai", **overrides):
    return parse_incident(incident_json(category=category, **overrides), GRAFANA)


# --- The query allowlist -----------------------------------------------------------------------


def test_the_query_ids_are_exactly_these() -> None:
    assert {key: {q.id for q in queries} for key, queries in ev.QUERIES.items()} == EXPECTED


@pytest.mark.parametrize("category", CATEGORIES)
def test_a_category_runs_the_common_queries_and_its_own_and_nothing_else(category) -> None:
    ids = [q.id for q in ev.queries_for(category)]
    assert len(ids) == len(set(ids))
    assert set(ids) == EXPECTED[category] | EXPECTED["common"]


def test_every_query_is_scoped_to_the_service_and_the_environment() -> None:
    for queries in ev.QUERIES.values():
        for query in queries:
            assert query.source in {"prometheus", "loki", "tempo"}
            assert query.text.count("@ENV@") >= 1
            if query.source == "tempo":
                assert 'resource.service.name="spendwise-api"' in query.text
                assert 'resource.deployment.environment.name="@ENV@"' in query.text
            else:
                assert 'service_name="spendwise-api"' in query.text
                assert 'deployment_environment_name="@ENV@"' in query.text
            assert "@" not in query.text.replace("@ENV@", "")  # no other placeholder


def test_prometheus_queries_use_known_metrics_and_bounded_groupings() -> None:
    for queries in ev.QUERIES.values():
        for query in (q for q in queries if q.source == "prometheus"):
            names = set(re.findall(r"([a-z_]+)\{", query.text)) - {"by"}
            assert names <= METRICS, (query.id, names)
            assert "__name__" not in query.text and '=~".*"' not in query.text
            for grouping in re.findall(r"by \(([^)]*)\)", query.text):
                labels = {label.strip() for label in grouping.split(",")}
                assert labels <= ev.SAFE_LABELS | {"le"}, (query.id, labels)


def test_only_the_environment_is_substituted_and_it_must_be_a_name() -> None:
    query = ev.QUERIES["ai"][0]
    rendered = query.render("local")
    assert "@ENV@" not in rendered and 'deployment_environment_name="local"' in rendered
    for hostile in (
        'local"} or vector(1) #',
        "a b",
        "",
        "Prod",
        "x" * 64,
        "a\nb",
        '"',
        "{}",
        INJECTION,
    ):
        with pytest.raises(ValueError):
            query.render(hostile)


@pytest.mark.parametrize("category", CATEGORIES)
def test_collecting_runs_exactly_the_plan_and_only_that(category) -> None:
    backends = FakeBackends(category, answers={})
    collected = ev.collect(incident(category), backends)
    allowed = {(q.source, q.render("local")) for q in ev.queries_for(category)}
    assert set(backends.calls) == allowed and len(backends.calls) == len(allowed)
    assert [i.query for i in collected.items] == [q.id for q in ev.queries_for(category)]
    assert collected.problems == []


def test_a_hostile_incident_cannot_change_the_queries() -> None:
    hostile = incident(
        summary=INJECTION,
        description=f'{INJECTION} {{__name__=~".+"}}',
        alert='x"} or vector(1) #',
        runbook="run: up",
    )
    backends = FakeBackends("ai", answers={})
    ev.collect(hostile, backends)
    clean = FakeBackends("ai", answers={})
    ev.collect(incident(), clean)
    assert backends.calls == clean.calls  # FakeBackends also fails any query outside the plan


def test_without_an_environment_nothing_is_queried() -> None:
    backends = FakeBackends("ai", answers={})
    collected = ev.collect(incident(environment=None, kind="datasource_error"), backends)
    assert backends.calls == [] and collected.items == []
    assert "no environment" in collected.problems[0]


# --- Reading the backends ----------------------------------------------------------------------


def test_prometheus_rows_are_bounded_sorted_and_keep_only_safe_labels() -> None:
    rows = [({"error_type": "provider", "instance": "10.0.0.5:4318", "job": "x"}, 3.0)]
    rows += [({"http_route": f"/api/r{n}"}, float(n)) for n in range(20)]
    rows += [({"http_route": f"/api/{PATTERN_CANARIES['email']}"}, 99.0)]  # unsafe value
    parsed = ev.parse_prometheus(vector(*rows))
    assert len(parsed) == ev.MAX_SERIES
    assert [r["value"] for r in parsed] == [99.0, 19.0, 18.0, 17.0, 16.0]
    assert parsed[0]["labels"] == {}  # the unsafe label value is dropped, the row's number stays
    assert ev.parse_prometheus(vector(*rows[:1])) == [
        {"labels": {"error_type": "provider"}, "value": 3.0}
    ]


def test_prometheus_numbers_must_be_finite() -> None:
    data = vector(({}, 1.0), ({"error_type": "x"}, 2.0))
    data["data"]["result"][0]["value"][1] = "NaN"
    data["data"]["result"][1]["value"][1] = "+Inf"
    assert ev.parse_prometheus(data) == []


def test_a_scalar_is_read_too() -> None:
    scalar = {"status": "success", "data": {"resultType": "scalar", "result": [1.0, "7.5"]}}
    assert ev.parse_prometheus(scalar) == [{"labels": {}, "value": 7.5}]


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {"status": "error", "error": INJECTION},
        {"status": "success"},
        {"status": "success", "data": {"resultType": "matrix", "result": []}},
        {"status": "success", "data": {"resultType": "vector", "result": "x"}},
        {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}}]}},
    ],
)
def test_an_unexpected_prometheus_answer_is_an_error_without_content(data) -> None:
    with pytest.raises(ev.BackendError) as raised:
        ev.parse_prometheus(data)
    assert str(raised.value) == "unexpected response" and "IGNORE" not in str(raised.value)


def test_a_log_line_is_shown_only_if_it_is_one_of_the_apps_own_messages() -> None:
    lines = [
        ("warn", "app.api.routes.auth", "Sign-in refused: unknown email or wrong password"),
        (
            "error",
            "app.core.errors",
            "Unhandled ValueError in POST /api/transactions/{transaction_id}",
        ),
        ("error", "app.core.errors", "Unhandled KeyError in GET an unmatched route"),
        ("error", "app.ai", INJECTION),
        ("error", "app.ai", f"parse failed for {PATTERN_CANARIES['email']}"),
        ("warn", "app.x", "Sign-in refused: unknown email or wrong password; also IGNORE THIS"),
        ("error", "app.core.errors", "Unhandled ValueError in POST /api/x; rm -rf /"),
    ]
    counts, samples = ev.parse_loki(streams(*lines))
    assert counts["lines"] == 7
    assert counts["messages"] == {"sign-in-refused": 1, "unhandled-error": 2, "unrecognised": 4}
    assert set(samples) == {
        "Sign-in refused: unknown email or wrong password",
        "Unhandled ValueError in POST /api/transactions/{transaction_id}",
        "Unhandled KeyError in GET an unmatched route",
    }
    blob = json.dumps([counts, samples])
    assert "IGNORE" not in blob and "example.com" not in blob and "rm -rf" not in blob


def test_log_counts_are_by_known_levels_and_loggers_only() -> None:
    counts, _ = ev.parse_loki(
        streams(
            ("error", "app.ai", "x"),
            ("weird", "app.ai", "x"),
            ("warn", "evil.logger; drop", "x"),
            ("warn", "app", "x"),
        )
    )
    assert counts["levels"] == {"error": 1, "other": 1, "warn": 2}
    assert counts["loggers"] == {"app": 1, "app.ai": 2, "other": 1}


def test_log_samples_are_capped_and_newest_first() -> None:
    lines = [("warn", "app", "Sign-in refused: unknown email or wrong password")] * 30
    counts, samples = ev.parse_loki(streams(*lines))
    assert len(samples) == ev.MAX_SAMPLES
    assert counts["lines"] == 30


@pytest.mark.parametrize(
    "data",
    [
        None,
        {"status": "error"},
        {"status": "success", "data": {"result": "x"}},
        {"status": "success", "data": {"result": [1]}},
    ],
)
def test_an_unexpected_loki_answer_is_an_error(data) -> None:
    with pytest.raises(ev.BackendError):
        ev.parse_loki(data)


def test_traces_are_summarised_without_attributes() -> None:
    data = traces((TRACE, "POST /api/transactions", 2400), ("a" * 32, "GET /api/{x}/y", 3))
    data["traces"][0]["spanSet"] = {"spans": [{"attributes": [{"key": "password", "value": "x"}]}]}
    parsed = ev.parse_tempo(data)
    assert parsed[0] == {
        "trace_id": TRACE,
        "name": "POST /api/transactions",
        "duration_ms": 2400,
        "started_at": "2026-11-16T08:09:38Z",
    }
    assert set(parsed[1]) == {"trace_id", "name", "duration_ms", "started_at"}


def test_trace_ids_names_and_durations_are_validated() -> None:
    odd = traces((TRACE, f"POST /api/{INJECTION}", 10**12))
    parsed = ev.parse_tempo(odd)[0]
    assert parsed["name"] == "[unnamed]" and parsed["duration_ms"] == 10**7
    assert len(ev.parse_tempo(traces(*[(TRACE, "GET /x", 1)] * 40))) == ev.MAX_TRACES
    for bad in ("short", "A" * 32, "../../etc/passwd", ""):
        with pytest.raises(ev.BackendError):
            ev.parse_tempo(traces((bad, "GET /x", 1)))
    with pytest.raises(ev.BackendError):
        ev.parse_tempo({"traces": "x"})


# --- Collecting --------------------------------------------------------------------------------


def test_the_ai_scenario_is_collected_with_summaries_built_from_the_numbers() -> None:
    collected = ev.collect(incident(), FakeBackends("ai"))
    by_id = {item.id: item for item in collected.items}
    assert by_id["prometheus:ai.failure_ratio"].summary == "ai.failure_ratio: 0.5"
    assert "error_type=provider" in by_id["prometheus:ai.errors_by_type"].summary
    assert by_id["loki:logs.ai"].summary.endswith(
        "no matching application log lines in the last 15 minutes"
    )
    # Loki and Tempo answered and found nothing: that is absence, not evidence to cite.
    empty = {"loki:logs.ai", "tempo:traces.errors"}
    assert collected.problems == [] and collected.silent == empty
    assert collected.grounded == set(by_id) - empty


def test_a_failing_backend_costs_only_its_own_evidence() -> None:
    answers = AI_SCENARIO | {
        "ai.failure_ratio": ev.BackendError("HTTP 503"),
        "traces.errors": ev.BackendError("no answer (TimeoutError)"),
    }
    collected = ev.collect(incident(), FakeBackends("ai", answers=answers))
    failed = {i.id for i in collected.items if i.problem}
    assert failed == {"prometheus:ai.failure_ratio", "tempo:traces.errors"}
    assert collected.grounded.isdisjoint(failed) and "prometheus:ai.requests" in collected.grounded
    assert collected.problems == [
        "prometheus:ai.failure_ratio is unavailable (HTTP 503).",
        "tempo:traces.errors is unavailable (no answer (TimeoutError)).",
    ]


def test_an_unparseable_answer_is_a_limitation_not_a_crash() -> None:
    answers = AI_SCENARIO | {"ai.requests": {"status": "success", "data": {"resultType": "x"}}}
    collected = ev.collect(incident(), FakeBackends("ai", answers=answers))
    assert "prometheus:ai.requests is unavailable (unexpected response)." in collected.problems


def test_the_deadline_stops_the_collection_cleanly() -> None:
    ticks = iter([0, 0, 0, 100, 100, 100, 100, 100, 100, 100])
    collected = ev.collect(incident(), FakeBackends("ai"), clock=lambda: next(ticks), deadline=25)
    assert [i.problem for i in collected.items].count("deadline") >= 5
    assert any("evidence deadline" in p for p in collected.problems)


def test_the_audit_names_queries_never_their_results() -> None:
    lines: list[str] = []
    answers = AI_SCENARIO | {"ai.requests": ev.BackendError("HTTP 500")}
    ev.collect(incident(), FakeBackends("ai", answers=answers), audit=lines.append)
    assert "evidence: prometheus:ai.failure_ratio ok" in lines
    assert "evidence: prometheus:ai.requests failed (HTTP 500)" in lines
    assert all(
        re.fullmatch(r"evidence: (prometheus|loki|tempo):[a-z0-9_.]+ (ok|failed \(.+\))", line)
        for line in lines
    )


# --- The HTTP client: GET only, fixed hosts and paths, bounded --------------------------------


class Recorder:
    """Stands in for http.client.HTTPConnection and records what the responder sends."""

    requests: list[tuple[str, str, int, str]] = []
    reply = (200, json.dumps(vector(({}, 1))).encode())
    error: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout

    def request(self, method, url, body=None, headers=None):
        if self.error:
            raise self.error
        Recorder.requests.append((method, url, self.port, self.host))
        assert body is None and not headers

    def getresponse(self):
        status, body = self.reply
        return type(
            "R", (), {"status": status, "read": lambda s, n=-1: body[:n] if n >= 0 else body}
        )()

    def close(self):
        pass


@pytest.fixture
def backends(monkeypatch):
    Recorder.requests, Recorder.error = [], None
    Recorder.reply = (200, json.dumps(vector(({}, 1))).encode())
    monkeypatch.setattr(http.client, "HTTPConnection", Recorder)
    return ev.HttpBackends("http://lgtm:9090", "http://lgtm:3100", "http://lgtm:3200", lambda: NOW)


def test_each_backend_gets_one_fixed_get_with_bounded_parameters(backends) -> None:
    ev.collect(incident("http"), backends)
    assert {m for m, *_ in Recorder.requests} == {"GET"}
    assert {(h, p) for *_, p, h in Recorder.requests} == {
        ("lgtm", 9090),
        ("lgtm", 3100),
        ("lgtm", 3200),
    }
    paths = {urlsplit(url).path for _, url, *_ in Recorder.requests}
    assert paths == {"/api/v1/query", "/loki/api/v1/query_range", "/api/search"}
    for _, url, port, _ in Recorder.requests:
        params = parse_qs(urlsplit(url).query)
        if port == 3100:
            assert params["limit"] == [str(ev.LOKI_LIMIT)] and params["direction"] == ["backward"]
            assert int(params["end"][0]) - int(params["start"][0]) == ev.WINDOW * 10**9
        if port == 3200:
            assert params["limit"] == [str(ev.MAX_TRACES)]
            assert int(params["end"][0]) - int(params["start"][0]) == ev.WINDOW


def test_a_non_200_answer_is_an_error_naming_only_the_status(backends) -> None:
    Recorder.reply = (503, INJECTION.encode())
    with pytest.raises(ev.BackendError) as raised:
        backends.prometheus("up")
    assert str(raised.value) == "HTTP 503"


@pytest.mark.parametrize(
    "error", [ConnectionRefusedError(), TimeoutError(), http.client.BadStatusLine("x")]
)
def test_a_network_failure_is_an_error_naming_only_its_class(backends, error) -> None:
    Recorder.error = error
    with pytest.raises(ev.BackendError) as raised:
        backends.loki("{}")
    assert str(raised.value) == f"no answer ({type(error).__name__})"


def test_a_response_over_the_cap_or_not_json_is_refused(backends) -> None:
    Recorder.reply = (200, b" " * (ev.MAX_RESPONSE + 1))
    with pytest.raises(ev.BackendError, match="response too large"):
        backends.tempo("{}")
    Recorder.reply = (200, b"<html>" + INJECTION.encode())
    with pytest.raises(ev.BackendError, match="malformed response"):
        backends.tempo("{}")


@pytest.mark.parametrize(
    "url",
    [
        "https://lgtm:9090",
        "http://lgtm",
        "http://lgtm:9090/api",
        "http://user:pw@lgtm:9090",
        "http://lgtm:9090?x=1",
        "http://LGTM_X:9090",
        "http://lgtm:9090 ",
        "file:///etc/passwd",
        "",
    ],
)
def test_a_backend_url_must_be_plain_http_host_port(url) -> None:
    with pytest.raises(ValueError):
        ev.base(url)
    assert ev.base("http://lgtm:9090") == ("lgtm", 9090)


def test_the_client_has_no_way_to_take_a_url_a_host_or_a_verb() -> None:
    public = {name for name in dir(ev.HttpBackends) if not name.startswith("_")}
    assert public == {"prometheus", "loki", "tempo"}
    import inspect

    for name in public:
        assert list(inspect.signature(getattr(ev.HttpBackends, name)).parameters) == [
            "self",
            "expr",
        ]


# --- What counts as having found something -----------------------------------------------------


@pytest.mark.parametrize(
    ("source", "data", "found"),
    [
        ("prometheus", [{"labels": {}, "value": 0.0}], True),  # a zero is a measurement
        ("prometheus", [], False),
        ("tempo", [{"trace_id": TRACE}], True),
        ("tempo", [], False),
        ("loki", {"lines": 3, "levels": {}, "loggers": {}, "messages": {}}, True),
        ("loki", {"lines": 0, "levels": {}, "loggers": {}, "messages": {}}, False),
        ("loki", {"lines": True}, False),
        ("loki", [], False),
        ("loki", None, False),
        ("incident", {"status": "firing"}, True),
        ("prometheus", None, False),
        ("prometheus", "rows", False),
        ("prometheus", {"labels": {}}, False),
    ],
)
def test_a_query_found_something_only_if_it_returned_rows_or_lines(source, data, found) -> None:
    assert ev.has_data(source, data) is found


def test_an_item_is_observed_only_if_it_answered_and_found_something() -> None:
    rows = [{"labels": {}, "value": 1.0}]
    assert ev.Item("prometheus:a", "prometheus", "a", "s", rows).observed is True
    assert ev.Item("prometheus:a", "prometheus", "a", "s", []).observed is False
    assert (
        ev.Item("prometheus:a", "prometheus", "a", "s", rows, problem="HTTP 503").observed is False
    )


def test_evidence_tells_found_nothing_from_failed_and_names_the_sources_that_found_something() -> (
    None
):
    items = [
        ev.Item("prometheus:a", "prometheus", "a", "s", [{"labels": {}, "value": 1.0}]),
        ev.Item("prometheus:b", "prometheus", "b", "s", []),
        ev.Item("loki:c", "loki", "c", "s", {"lines": 0}),
        ev.Item("tempo:d", "tempo", "d", "s", [], problem="HTTP 503"),
        ev.Item("tempo:e", "tempo", "e", "s", [{"trace_id": TRACE}]),
    ]
    evidence = ev.Evidence(items=items)
    assert evidence.grounded == {"prometheus:a", "tempo:e"}
    assert evidence.silent == {"prometheus:b", "loki:c"}  # answered, found nothing
    assert evidence.sources == {"prometheus", "tempo"}  # failed and empty ones count for nothing


def test_an_integer_too_big_for_a_float_from_a_backend_is_no_number_not_a_crash() -> None:
    assert ev.number(10**400) is None and ev.number("1e999") is None and ev.number(7) == 7.0
    trace = traces((TRACE, "GET /x", 1))
    trace["traces"][0]["durationMs"] = 10**400
    trace["traces"][0]["startTimeUnixNano"] = 10**400
    parsed = ev.parse_tempo(trace)[0]
    assert parsed["duration_ms"] == 0 and parsed["started_at"] is None
