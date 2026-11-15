"""End to end: the API's traces, metrics and logs reach the OpenTelemetry Collector.

The real image, PostgreSQL and the pinned Collector run in Compose (compose.observability.yaml).
Real HTTP traffic goes to the app, and the tests read back what the Collector received: its
debug exporter's output (every span, metric data point and log record, with their resource) and
its own counters of accepted and exported items. A running container proves nothing by itself;
these do. Nothing goes to Grafana, AWS, Render or the internet.
"""

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest

from integration.stack import Stack
from observability_smoke.collector_output import Received, received

# How long the Collector may take to print what the app sent (the app exports spans every second
# and metrics every 5 s in this stack; the Collector batches for 1 s).
DEADLINE = 90
POLL = 1.0
SIGN_IN_REFUSED = "Sign-in refused: unknown email or wrong password"
TRANSACTION_ROUTE = "/api/transactions/{transaction_id}"
QUERY_MARKER = "otel-smoke-query-" + secrets.token_hex(4)
# Distinctive enough never to turn up by chance (e.g. in a timestamp's nanoseconds).
AMOUNT_CENTS = 987_654_321_07

# The Collector's own counters, read from inside the app container: the Collector's internal
# metrics port is on the internal network only, like everything else about it.
SCRAPE = (
    "import urllib.request; "
    "print(urllib.request.urlopen('http://otel-collector:8888/metrics', timeout=5).read().decode())"
)


def wait_for(what: str, check: Callable[[], object], deadline: float = DEADLINE):
    """Poll `check` until it returns something truthy, at most `deadline` seconds."""
    end = time.monotonic() + deadline
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > end:
            pytest.fail(f"Timed out after {deadline}s waiting for {what}")
        time.sleep(POLL)


def collector_log(stack: Stack) -> str:
    return stack.compose("logs", "--no-color", "otel-collector", timeout=60).stdout


def collector_counters(stack: Stack) -> dict[str, float]:
    """otelcol_receiver_* and otelcol_exporter_* counters, summed over their labels."""
    text = stack.compose("exec", "-T", "app", "python", "-c", SCRAPE, timeout=60).stdout
    counters: dict[str, float] = {}
    for name, value in re.findall(
        r"^(otelcol_(?:receiver|exporter)_\w+?)(?:_total)?(?:\{[^}]*\})? (\S+)$", text, re.M
    ):
        counters[name] = counters.get(name, 0.0) + float(value)
    return counters


@dataclass
class Traffic:
    """What the tests sent, so they can look for it, or make sure it is absent."""

    email: str
    password: str
    wrong_password: str
    session: str
    description: str
    transaction_id: int


@pytest.fixture(scope="module")
def traffic(stack: Stack) -> Traffic:
    """Representative traffic: probes, sign-up, data, a refused sign-in, a 404, sign-out."""
    wait_for(
        "the Collector to start",
        lambda: "Everything is ready. Begin running and processing data." in collector_log(stack),
    )
    email = f"otel-{secrets.token_hex(6)}@example.com"
    password, wrong_password = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    description = f"Rent to landlord {secrets.token_hex(6)}"
    with httpx.Client(base_url=stack.base_url, timeout=30) as client:
        for probe in ("/api/health", "/api/health/ready", "/api/meta"):
            assert client.get(probe).status_code == 200
        signup = client.post("/api/auth/signup", json={"email": email, "password": password})
        assert signup.status_code == 201, signup.text
        session = client.cookies["spendwise_session"]
        category = client.get("/api/categories").json()[0]
        created = client.post(
            "/api/transactions",
            params={"marker": QUERY_MARKER},
            json={
                "amount_cents": AMOUNT_CENTS,
                "type": category["type"],
                "category_id": category["id"],
                "description": description,
                "occurred_on": "2026-11-15",
            },
        )
        assert created.status_code == 201, created.text
        transaction_id = created.json()["id"]
        assert client.get(f"/api/transactions/{transaction_id}").status_code == 200
        assert client.get("/api/analytics/summary").status_code == 200
        refused = client.post("/api/auth/login", json={"email": email, "password": wrong_password})
        assert refused.status_code == 401
        assert client.get("/api/transactions/999999999").status_code == 404
        assert client.post("/api/auth/logout").status_code == 204
    return Traffic(email, password, wrong_password, session, description, transaction_id)


@pytest.fixture(scope="module")
def collected(stack: Stack, traffic: Traffic) -> Received:
    """What the Collector printed, once every signal of the traffic above has arrived."""

    def complete() -> Received | None:
        output = received(collector_log(stack))
        has_trace = output.spans_named("POST /api/auth/login")
        has_log = output.logs_saying(SIGN_IN_REFUSED)
        has_metric = [
            p
            for p in output.points_of("http.server.request.duration")
            if p.get("http.route") == TRANSACTION_ROUTE
        ]
        return output if has_trace and has_log and has_metric else None

    return wait_for("a span, a log record and a metric data point at the Collector", complete)


# --- All three signals arrived, with the same resource --------------------------------------


def test_traces_reach_the_collector(collected: Received) -> None:
    names = {span.name for span in collected.spans}
    assert {
        "POST /api/auth/signup",
        "POST /api/transactions",
        f"GET {TRANSACTION_ROUTE}",
        "GET /api/analytics/summary",
        "POST /api/auth/login",
        "POST /api/auth/logout",
    } <= names
    reads = collected.spans_named(f"GET {TRANSACTION_ROUTE}")
    assert reads
    read = next(s for s in reads if s.attributes["http.response.status_code"] == "200")
    assert read.attributes["http.route"] == TRANSACTION_ROUTE
    assert read.attributes["http.request.method"] == "GET"
    assert re.fullmatch(r"[0-9a-f]{32}", read.trace_id)


def test_probes_are_not_traced(collected: Received) -> None:
    for span in collected.spans:
        assert span.attributes.get("url.path") not in (
            "/api/health",
            "/api/health/ready",
            "/api/meta",
        )


def test_metrics_reach_the_collector_with_route_templates(collected: Received, traffic) -> None:
    names = {metric.name for metric in collected.metrics}
    assert {"http.server.request.duration", "http.server.active_requests"} <= names
    units = {m.unit for m in collected.metrics if m.name == "http.server.request.duration"}
    assert units == {"s"}
    routes = {p.get("http.route") for p in collected.points_of("http.server.request.duration")}
    assert TRANSACTION_ROUTE in routes
    for point in collected.points_of("http.server.request.duration"):
        assert str(traffic.transaction_id) not in point.values()  # the template, never the path
        assert set(point) <= {
            "http.request.method",
            "http.route",
            "http.response.status_code",
            "error.type",
            "url.scheme",
            "network.protocol.name",
            "network.protocol.version",
        }


def test_logs_reach_the_collector_with_their_trace(collected: Received) -> None:
    (login,) = collected.spans_named("POST /api/auth/login")
    (refused,) = collected.logs_saying(SIGN_IN_REFUSED)
    assert refused.severity == "WARN"
    assert (refused.trace_id, refused.span_id) == (login.trace_id, login.span_id)
    (signup,) = collected.spans_named("POST /api/auth/signup")
    (created,) = collected.logs_saying("Account created")
    assert created.trace_id == signup.trace_id
    # Logged at startup, outside any request: no trace.
    started = [r for r in collected.logs if r.body.startswith("SpendWise API started")]
    assert started and started[0].trace_id == ""


def test_every_signal_names_the_same_service_version_and_environment(
    collected: Received, stack: Stack
) -> None:
    expected = {
        "service.name": "spendwise-api",
        "service.version": stack.app_version,  # the APP_VERSION the stack was started with
        "deployment.environment.name": "local",  # the local Compose stack (compose.override.yaml)
    }
    for signal in ("traces", "metrics", "logs"):
        blocks = collected.of(signal)
        assert blocks, signal
        for block in blocks:
            assert expected.items() <= block.resource.items(), (signal, block.resource)
            assert "deployment.environment" not in block.resource


def test_the_collector_counted_every_signal_and_refused_none(stack: Stack, collected) -> None:
    counters = collector_counters(stack)
    for signal in ("spans", "metric_points", "log_records"):
        assert counters.get(f"otelcol_receiver_accepted_{signal}", 0) > 0, (signal, counters)
        assert counters.get(f"otelcol_exporter_sent_{signal}", 0) > 0, (signal, counters)
        assert counters.get(f"otelcol_receiver_refused_{signal}", 0) == 0, (signal, counters)
        assert counters.get(f"otelcol_receiver_failed_{signal}", 0) == 0, (signal, counters)


# --- Privacy, checked on everything the Collector received ----------------------------------


def test_nothing_sensitive_reached_the_collector(stack: Stack, traffic: Traffic, collected) -> None:
    everything = collector_log(stack)
    assert "POST /api/transactions" in everything  # the traffic is in there...
    for secret in (
        traffic.email,
        traffic.password,
        traffic.wrong_password,
        traffic.session,
        traffic.description,
        str(AMOUNT_CENTS),  # the amount
        QUERY_MARKER,
        stack.db_password,
        "python-httpx",  # the client's browser (User-Agent)
        "client.address",
        "user_agent.original",
        "url.query",
        "http.request.header",
        "http.response.header",
    ):
        assert secret not in everything, secret  # ...but none of this


# --- Without the Collector --------------------------------------------------------------------


@pytest.mark.stops_collector
def test_the_app_keeps_serving_while_the_collector_is_down_and_telemetry_resumes(
    stack: Stack, collected
) -> None:
    stack.compose("stop", "otel-collector")
    try:
        with httpx.Client(base_url=stack.base_url, timeout=30) as client:
            for _ in range(10):
                started = time.monotonic()
                assert client.get("/api/categories").status_code == 401
                assert time.monotonic() - started < 2  # never waits for telemetry
            email = f"otel-down-{secrets.token_hex(6)}@example.com"
            signup = client.post(
                "/api/auth/signup", json={"email": email, "password": secrets.token_urlsafe(18)}
            )
            assert signup.status_code == 201
        services = stack.services()
        assert services["app"]["State"] == "running"
        assert services["app"]["Health"] == "healthy"
    finally:
        stack.compose("start", "otel-collector")

    # Back up: new requests are exported again, without restarting the app.
    marker = f"/api/transactions/{secrets.randbelow(10**9) + 10**9}"
    with httpx.Client(base_url=stack.base_url, timeout=30) as client:

        def exported_again() -> bool:
            assert client.get(marker).status_code == 401
            return any(
                s.attributes.get("url.path") == marker for s in received(collector_log(stack)).spans
            )

        wait_for("telemetry to resume after the Collector restarted", exported_again)
