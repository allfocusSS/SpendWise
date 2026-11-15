"""OpenTelemetry in the running API: spans, HTTP metrics and logs, and what they never contain.

The app is instrumented with in-memory exporters (and, for the OTLP wire format, a local HTTP
receiver on 127.0.0.1), so nothing leaves the machine. The process-wide setup, which sets
OpenTelemetry's global providers once, runs in a subprocess. docs/observability.md has the
policy these tests hold the code to.
"""

import gzip
import http.server
import json
import logging
import os
import re
import socket
import socketserver
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from sqlalchemy import text

from app.api.deps import CurrentUser, DbSession
from app.core.config import Settings
from app.models import Category
from app.observability import (
    APP_LOGGER,
    Telemetry,
    build_telemetry,
    get_meter,
    get_tracer,
    instrument_app,
    setup_telemetry,
)
from app.observability.privacy import EXCEPTION_EVENT_ATTRIBUTES, HTTP_METRIC_ATTRIBUTES
from tests.conftest import ALICE, PASSWORD

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
SECRET_NOTE = "rent for flat 12 paid to Askar Nurlanovich 250000"
QUERY_MARKER = "otel-query-marker-7f3a"
BEARER = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzcGVuZHdpc2UifQ.c2lnbmF0dXJlLXNlY3JldA"


def telemetry_settings(**values) -> Settings:
    defaults = {
        "otel_enabled": True,
        "otel_exporter_otlp_endpoint": "http://otel-collector.invalid:4318",
        "app_env": "test",
        "app_version": SHA,
    }
    return Settings(_env_file=None, **(defaults | values))


@dataclass
class Captured:
    """One Telemetry with in-memory exporters, and what it exported."""

    telemetry: Telemetry
    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader
    logs: InMemoryLogRecordExporter

    def instrument(self, app: FastAPI) -> TestClient:
        instrument_app(app, self.telemetry)
        return TestClient(app, raise_server_exceptions=False)

    def finished_spans(self):
        self.telemetry.force_flush()
        return self.spans.get_finished_spans()

    def server_spans(self) -> dict[str, list]:
        by_name: dict[str, list] = {}
        for span in self.finished_spans():
            by_name.setdefault(span.name, []).append(span)
        return by_name

    def log_records(self):
        self.telemetry.force_flush()
        return [readable.log_record for readable in self.logs.get_finished_logs()]

    def metric_points(self) -> list[tuple[str, str, dict]]:
        """(metric name, unit, attributes) of every data point collected so far."""
        data = self.metrics.get_metrics_data()
        return [
            (metric.name, metric.unit, dict(point.attributes))
            for resource_metrics in (data.resource_metrics if data else [])
            for scope in resource_metrics.scope_metrics
            for metric in scope.metrics
            for point in metric.data.data_points
        ]

    def everything_exported(self) -> str:
        """All exported spans, events, metric attributes and log records, as one text."""
        parts = []
        for span in self.finished_spans():
            parts.append(span.to_json())
        for _name, _unit, attributes in self.metric_points():
            parts.append(json.dumps(attributes, default=str))
        for readable in self.logs.get_finished_logs():
            parts.append(readable.to_json())
        return "\n".join(parts)


def build_captured(**values) -> Captured:
    spans, metrics, logs = (
        InMemorySpanExporter(),
        InMemoryMetricReader(),
        InMemoryLogRecordExporter(),
    )
    telemetry = build_telemetry(
        telemetry_settings(**values),
        span_exporter=spans,
        metric_readers=[metrics],
        log_exporter=logs,
    )
    logging.getLogger(APP_LOGGER).addHandler(telemetry.log_handler)  # as setup_telemetry does
    return Captured(telemetry, spans, metrics, logs)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[Captured]:
    # instrument_app() sets this for the process; monkeypatch puts the old value back afterwards.
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    captured = build_captured()
    yield captured
    captured.telemetry.shutdown()


def sign_up(client: TestClient, email: str = ALICE) -> None:
    response = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text


# --- Traces ----------------------------------------------------------------------------------


def test_requests_become_server_spans_named_after_their_route(app, captured) -> None:
    client = captured.instrument(app)
    sign_up(client)
    groceries = client.get("/api/categories").json()[0]
    created = client.post(
        "/api/transactions",
        json={
            "amount_cents": 250000,
            "type": groceries["type"],
            "category_id": groceries["id"],
            "description": "Groceries",
            "occurred_on": "2026-11-15",
        },
    )
    assert created.status_code == 201, created.text
    assert client.get(f"/api/transactions/{created.json()['id']}").status_code == 200

    spans = captured.server_spans()
    assert set(spans) >= {
        "POST /api/auth/signup",
        "GET /api/categories",
        "POST /api/transactions",
        "GET /api/transactions/{transaction_id}",
    }
    (read,) = spans["GET /api/transactions/{transaction_id}"]
    assert read.kind == SpanKind.SERVER
    assert read.attributes["http.route"] == "/api/transactions/{transaction_id}"
    assert read.attributes["http.request.method"] == "GET"
    assert read.attributes["http.response.status_code"] == 200
    assert read.end_time > read.start_time  # the request's duration
    # The resource of every span: this service, its exact version and its environment.
    assert read.resource.attributes["service.name"] == "spendwise-api"
    assert read.resource.attributes["service.version"] == SHA
    assert read.resource.attributes["deployment.environment.name"] == "test"
    # One span per request: no ASGI receive/send child spans.
    assert all(span.kind == SpanKind.SERVER for span in captured.finished_spans())


def test_probes_are_neither_traced_nor_measured(app, captured) -> None:
    client = captured.instrument(app)
    for path in ("/api/health", "/api/health/ready", "/api/meta"):
        assert client.get(path).status_code == 200
    assert client.get("/api/categories").status_code == 401  # an ordinary request, for contrast

    assert list(captured.server_spans()) == ["GET /api/categories"]
    routes = {
        attributes.get("http.route")
        for name, _unit, attributes in captured.metric_points()
        if name == "http.server.request.duration"
    }
    assert routes == {"/api/categories"}


def test_unmatched_paths_have_no_route(app, captured) -> None:
    client = captured.instrument(app)
    assert client.get("/api/no/such/thing/123").status_code == 404
    (span,) = captured.finished_spans()
    assert span.name == "GET"
    assert "http.route" not in span.attributes


# --- Metrics ---------------------------------------------------------------------------------


def test_http_metrics_use_route_templates_and_bounded_attributes(app, captured) -> None:
    client = captured.instrument(app)
    sign_up(client)
    for transaction_id in (101, 202, 303):
        assert client.get(f"/api/transactions/{transaction_id}").status_code == 404
    assert client.get("/api/categories/nothing-like-an-id").status_code == 422

    points = captured.metric_points()
    names = {name for name, _unit, _attributes in points}
    assert {"http.server.request.duration", "http.server.active_requests"} <= names
    durations = [a for name, unit, a in points if name == "http.server.request.duration"]
    assert {unit for name, unit, _a in points if name == "http.server.request.duration"} == {"s"}
    # Three different IDs, one series: the route template, never the path.
    transaction_reads = [
        a for a in durations if a.get("http.route") == "/api/transactions/{transaction_id}"
    ]
    assert len(transaction_reads) == 1
    assert transaction_reads[0]["http.response.status_code"] == 404
    for _name, _unit, attributes in points:
        assert set(attributes) <= HTTP_METRIC_ATTRIBUTES
        values = " ".join(str(v) for v in attributes.values())
        for unbounded in ("101", "202", "303", "nothing-like-an-id", "testserver", ALICE):
            assert unbounded not in values


def test_metrics_and_logs_do_not_depend_on_trace_sampling(app, monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    captured = build_captured(otel_traces_sample_ratio=0.0)
    try:
        client = captured.instrument(app)
        sign_up(client)
        assert captured.finished_spans() == ()  # no trace kept at ratio 0
        assert any(name == "http.server.request.duration" for name, *_ in captured.metric_points())
        assert [r.body for r in captured.log_records()] == ["Account created"]
    finally:
        captured.telemetry.shutdown()


# --- Logs ------------------------------------------------------------------------------------


def test_application_logs_carry_the_trace_context_of_their_request(app, captured) -> None:
    client = captured.instrument(app)
    sign_up(client)
    refused = client.post("/api/auth/login", json={"email": ALICE, "password": "wrong password"})
    assert refused.status_code == 401

    (login,) = captured.server_spans()["POST /api/auth/login"]
    (warning,) = [r for r in captured.log_records() if r.severity_text == "WARN"]
    assert warning.body == "Sign-in refused: unknown email or wrong password"
    assert warning.trace_id == login.context.trace_id
    assert warning.span_id == login.context.span_id
    # Only what the record itself says: no file paths, no console formatting fields.
    assert set(warning.attributes or {}) == set()


def test_unhandled_errors_are_logged_and_traced_without_their_data(app, captured) -> None:
    def broken_query(db: DbSession) -> None:
        db.execute(text("SELECT * FROM no_such_table WHERE note = :note"), {"note": SECRET_NOTE})

    app.add_api_route("/api/broken", broken_query, methods=["GET"])
    client = captured.instrument(app)
    response = client.get("/api/broken")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"  # Starlette's own answer, unchanged

    (span,) = captured.server_spans()["GET /api/broken"]
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is None
    assert span.attributes["error.type"] == "500"
    (exception,) = [event for event in span.events if event.name == "exception"]
    assert set(exception.attributes) <= EXCEPTION_EVENT_ATTRIBUTES  # the type, no message
    # OperationalError on SQLite, ProgrammingError on PostgreSQL: a missing table either way.
    error_type = exception.attributes["exception.type"].removeprefix("sqlalchemy.exc.")
    assert error_type in ("OperationalError", "ProgrammingError")
    (error,) = [r for r in captured.log_records() if r.severity_text == "ERROR"]
    assert error.body == f"Unhandled {error_type} in GET /api/broken"
    assert error.trace_id == span.context.trace_id
    # The statement's values never reach a span or a log (hide_parameters, app/core/db.py).
    assert SECRET_NOTE not in captured.everything_exported()


def exported_exceptions(captured: Captured) -> list[dict]:
    return [
        dict(event.attributes)
        for span in captured.finished_spans()
        for event in span.events
        if event.name == "exception"
    ]


def test_exception_messages_never_leave_the_process(app, captured) -> None:
    # A realistic bug: code that puts what it was handling into the exception's message.
    def parse_description() -> None:
        raise ValueError(f"cannot categorize {SECRET_NOTE!r} for {ALICE}")

    app.add_api_route("/api/categorize", parse_description, methods=["GET"])
    client = captured.instrument(app)
    assert client.get("/api/categorize").status_code == 500

    assert exported_exceptions(captured) == [
        {"exception.type": "ValueError", "exception.escaped": "False"}
    ]
    (error,) = [r for r in captured.log_records() if r.severity_text == "ERROR"]
    assert error.body == "Unhandled ValueError in GET /api/categorize"
    exported = captured.everything_exported()
    for secret in (SECRET_NOTE, ALICE, "cannot categorize", "Traceback"):
        assert secret not in exported, secret


def test_a_constraint_violation_does_not_leak_what_the_database_reports(app, captured) -> None:
    # Two concurrent POST /api/categories with the same name end like this. On PostgreSQL (the
    # suite's TEST_DATABASE_URL run) the error's DETAIL line quotes the name:
    # "Key (user_id, name, type)=(1, <name>, expense) already exists".
    name = "Category for Askar Nurlanovich 42"

    def create_twice(db: DbSession, user: CurrentUser) -> None:
        for _ in range(2):
            db.add(Category(user_id=user.id, name=name, type="expense"))
            db.commit()

    app.add_api_route("/api/create-twice", create_twice, methods=["POST"])
    client = captured.instrument(app)
    sign_up(client)
    assert client.post("/api/create-twice").status_code == 500

    (exception,) = exported_exceptions(captured)
    assert exception["exception.type"] == "sqlalchemy.exc.IntegrityError"
    assert set(exception) <= EXCEPTION_EVENT_ATTRIBUTES
    assert name not in captured.everything_exported()


def test_spans_of_application_code_do_not_export_exception_messages(captured) -> None:
    # The SDK itself describes a failed span's status as "Type: message".
    tracer = captured.telemetry.tracer_provider.get_tracer("tests")
    with pytest.raises(RuntimeError), tracer.start_as_current_span("categorize"):
        raise RuntimeError(f"bad input {SECRET_NOTE}")
    (span,) = captured.finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is None
    assert exported_exceptions(captured) == [
        {"exception.type": "RuntimeError", "exception.escaped": "False"}
    ]
    assert SECRET_NOTE not in captured.everything_exported()


def test_application_code_never_logs_exception_details() -> None:
    # The OpenTelemetry handler exports a logged exception's message and stack trace as
    # attributes, so SpendWise logs name the exception type only (see app/core/errors.py).
    for path in (BACKEND / "app").rglob("*.py"):
        source = path.read_text()
        for forbidden in ("exc_info", "log.exception(", "logger.exception(", "stack_info"):
            assert forbidden not in source, (path, forbidden)


def test_url_paths_carry_no_free_text(anon_client) -> None:
    # url.path is required by the HTTP semantic conventions and kept on spans (http.route is what
    # metrics use). It holds no user text or secrets: every API path parameter is an integer ID,
    # the frontend's routes are fixed names, and query strings are dropped.
    spec = anon_client.get("/openapi.json").json()
    parameters = [
        (path, parameter["name"], parameter["schema"].get("type"))
        for path, operations in spec["paths"].items()
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "path"
    ]
    assert parameters, "expected path parameters"
    assert {kind for _path, _name, kind in parameters} == {"integer"}, parameters
    app_routes = (REPO / "frontend" / "src" / "App.tsx").read_text()
    assert ":" not in "".join(re.findall(r'path="([^"]*)"', app_routes))  # no route parameters


def test_one_record_per_log_call(app, captured) -> None:
    client = captured.instrument(app)
    # A second create_app() (as tests do all the time) adds no second handler.
    from app.main import create_app

    create_app()
    sign_up(client)
    assert [r.body for r in captured.log_records()].count("Account created") == 1
    otel_handlers = [
        h for h in logging.getLogger(APP_LOGGER).handlers if h is captured.telemetry.log_handler
    ]
    assert len(otel_handlers) == 1


def test_only_app_loggers_are_exported(captured) -> None:
    logging.getLogger("app.services.example").info("from the app")
    logging.getLogger("uvicorn.access").warning('127.0.0.1 - "GET /api/x?y=1 HTTP/1.1" 200')
    logging.getLogger("sqlalchemy.engine").warning("SELECT secret")
    logging.getLogger("opentelemetry.exporter.otlp").warning("Failed to export batch")
    logging.getLogger("app.debugging").debug("below INFO")
    assert [r.body for r in captured.log_records()] == ["from the app"]


# --- Privacy ---------------------------------------------------------------------------------


def test_nothing_sensitive_is_exported_even_when_header_capture_is_requested(
    app, captured, monkeypatch
) -> None:
    # An operator asking the instrumentation for every header must still not export any.
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST", ".*")
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_RESPONSE", ".*")
    client = captured.instrument(app)

    sign_up(client)
    session = client.cookies.get("spendwise_session")
    assert session
    groceries = client.get("/api/categories").json()[0]
    created = client.post(
        f"/api/transactions?marker={QUERY_MARKER}",
        json={
            "amount_cents": 777777,
            "type": groceries["type"],
            "category_id": groceries["id"],
            "description": SECRET_NOTE,
            "occurred_on": "2026-11-15",
        },
        headers={"Authorization": f"Bearer {BEARER}", "User-Agent": "Secret-Browser/1.0"},
    )
    assert created.status_code == 201, created.text
    client.post("/api/auth/login", json={"email": ALICE, "password": "the wrong one"})
    client.post("/api/auth/logout")

    exported = captured.everything_exported()
    assert "POST /api/transactions" in exported  # the requests were exported...
    for secret in (
        PASSWORD,
        "the wrong one",
        ALICE,
        session,
        BEARER,
        SECRET_NOTE,
        "777777",
        QUERY_MARKER,
        "Secret-Browser",
        "testclient",  # the client's address
        "http.request.header",
        "http.response.header",
        "set_cookie",
        "not-a-real",  # any database credential
    ):
        assert secret not in exported, secret  # ...without any of this


def test_no_header_capture_is_configured() -> None:
    from app.observability import telemetry

    source = Path(telemetry.__file__).read_text()
    assert "http_capture_headers" not in source


# --- Wire format: OTLP/HTTP to the configured endpoint ---------------------------------------


class _OtlpReceiver(http.server.BaseHTTPRequestHandler):
    requests: list[tuple[str, str, bytes]] = []

    def do_POST(self) -> None:  # noqa: N802 (http.server's name)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        self.requests.append((self.path, self.headers["Content-Type"], body))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


@pytest.fixture
def otlp_receiver() -> Iterator[tuple[str, list]]:
    _OtlpReceiver.requests = []
    # A plain TCPServer: HTTPServer looks up the host's name first, which can take seconds.
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _OtlpReceiver)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", _OtlpReceiver.requests
    server.shutdown()
    server.server_close()


def test_all_three_signals_go_to_the_otlp_endpoint(app, otlp_receiver, monkeypatch) -> None:
    endpoint, received = otlp_receiver
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    telemetry = build_telemetry(telemetry_settings(otel_exporter_otlp_endpoint=endpoint + "/"))
    logging.getLogger(APP_LOGGER).addHandler(telemetry.log_handler)
    try:
        instrument_app(app, telemetry)
        client = TestClient(app)
        sign_up(client)
        assert telemetry.force_flush()
    finally:
        telemetry.shutdown()

    paths = {path for path, _type, _body in received}
    assert paths == {"/v1/traces", "/v1/metrics", "/v1/logs"}
    assert {content_type for _p, content_type, _b in received} == {"application/x-protobuf"}

    def resources(path: str, message):
        decoded = []
        for p, _t, body in received:
            if p == path:
                request = message()
                request.ParseFromString(body)
                decoded.append(request)
        return decoded

    expected = {
        "service.name": "spendwise-api",
        "service.version": SHA,
        "deployment.environment.name": "test",
    }
    for path, message, field in (
        ("/v1/traces", ExportTraceServiceRequest, "resource_spans"),
        ("/v1/metrics", ExportMetricsServiceRequest, "resource_metrics"),
        ("/v1/logs", ExportLogsServiceRequest, "resource_logs"),
    ):
        for request in resources(path, message):
            for item in getattr(request, field):
                attributes = {kv.key: kv.value.string_value for kv in item.resource.attributes}
                assert expected.items() <= attributes.items(), (path, attributes)


# --- Failure behavior ------------------------------------------------------------------------


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]  # closed again when the socket is


def test_an_unreachable_collector_never_breaks_a_request(app, monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    endpoint = f"http://127.0.0.1:{closed_port()}"
    telemetry = build_telemetry(telemetry_settings(otel_exporter_otlp_endpoint=endpoint))
    logging.getLogger(APP_LOGGER).addHandler(telemetry.log_handler)
    instrument_app(app, telemetry)
    client = TestClient(app)
    try:
        sign_up(client)
        for _ in range(5):
            assert client.get("/api/categories").status_code == 200
        assert (
            client.post("/api/auth/login", json={"email": ALICE, "password": "x"}).status_code
            == 401
        )
    finally:
        started = time.monotonic()
        telemetry.shutdown()
        assert time.monotonic() - started < 20  # bounded, though every export fails


# --- Telemetry off, and the process-wide setup -------------------------------------------------


def test_telemetry_off_has_no_side_effects(monkeypatch) -> None:
    from opentelemetry.sdk.trace import TracerProvider

    threads = set(threading.enumerate())
    handlers = list(logging.getLogger(APP_LOGGER).handlers)
    off = Settings(_env_file=None, otel_enabled=False)

    assert setup_telemetry(off) is None
    assert set(threading.enumerate()) == threads  # no exporter or reader thread
    assert logging.getLogger(APP_LOGGER).handlers == handlers
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)  # no SDK installed
    # The public API still works and records nothing.
    with get_tracer("tests").start_as_current_span("noop") as span:
        assert not span.is_recording()
    get_meter("tests").create_counter("noop").add(1)


PROCESS_CHECK = textwrap.dedent(
    """
    import logging, sys, threading, time
    from fastapi.testclient import TestClient
    from opentelemetry import metrics, trace

    from app.main import app, create_app
    from app.observability import APP_LOGGER, get_tracer, setup_telemetry
    from app.core.config import get_settings

    telemetry = setup_telemetry(get_settings())
    assert telemetry is not None
    assert setup_telemetry(get_settings()) is telemetry  # once per process
    create_app(); create_app()
    handlers = [h for h in logging.getLogger(APP_LOGGER).handlers if h is telemetry.log_handler]
    assert len(handlers) == 1, handlers
    assert not any(h is telemetry.log_handler for h in logging.getLogger().handlers)
    assert trace.get_tracer_provider() is telemetry.tracer_provider
    assert metrics.get_meter_provider() is telemetry.meter_provider
    with get_tracer("check").start_as_current_span("check") as span:
        assert span.is_recording()

    # The lifespan's shutdown flushes and stops everything, in bounded time, with no
    # Collector to talk to.
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        started = time.monotonic()
    elapsed = time.monotonic() - started
    assert telemetry.log_handler not in logging.getLogger(APP_LOGGER).handlers
    left = [t.name for t in threading.enumerate() if t.name.startswith("Otel")]
    assert not left, left
    print(f"ok {elapsed:.1f}s")
    """
)


# --- The deployed environments as they are configured today: telemetry off ------------------

STARTUP_CHECK = textwrap.dedent(
    """
    import logging, socket, sys, threading
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider

    connections = []  # any network connection at all, OTLP or other
    real_connect = socket.socket.connect
    def record(self, address):
        connections.append(address)
        return real_connect(self, address)
    socket.socket.connect = record

    from fastapi.testclient import TestClient
    from app.main import app
    from app.observability import APP_LOGGER

    with TestClient(app) as client:  # startup and shutdown (the lifespan) included
        meta = client.get("/api/meta").json()
    assert meta == {"environment": sys.argv[1], "version": sys.argv[2]}, meta
    assert not isinstance(trace.get_tracer_provider(), TracerProvider)
    assert not isinstance(metrics.get_meter_provider(), MeterProvider)
    assert not [t.name for t in threading.enumerate() if t.name.startswith("Otel")]
    assert [h.get_name() for h in logging.getLogger(APP_LOGGER).handlers] == ["spendwise-console"]
    assert connections == [], connections
    print("ok")
    """
)


def render_environment() -> dict[str, str]:
    """Development's variables: render.yaml, plus what Render adds and what it kept."""
    (service,) = yaml.safe_load((REPO / "render.yaml").read_text())["services"]
    env = {v["key"]: v["value"] for v in service["envVars"] if "value" in v}
    return env | {
        "DATABASE_URL": "postgresql://spendwise:x@dpg-internal.invalid/spendwise",  # fromDatabase
        "RENDER": "true",
        "RENDER_GIT_COMMIT": SHA,
        "PORT": "10000",
        "ENVIRONMENT": "production",  # the variable render.yaml no longer lists
    }


def aws_environment() -> dict[str, str]:
    """Production's variables: compose.yaml with deploy/aws/compose.aws.yaml, interpolated with
    their defaults, and APP_VERSION as the deploy wrapper exports it."""
    base = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]["app"]["environment"]
    aws = yaml.safe_load((REPO / "deploy" / "aws" / "compose.aws.yaml").read_text())
    merged = base | aws["services"]["app"]["environment"]

    def interpolate(value: str) -> str:
        return re.sub(r"\$\{(\w+):-([^}]*)\}", lambda m: m.group(2), str(value))

    env = {key: interpolate(value) for key, value in merged.items()}
    return env | {"APP_VERSION": SHA}


@pytest.mark.parametrize(
    ("environment", "variables"),
    [("development", render_environment), ("production", aws_environment)],
)
def test_deployed_environments_start_with_telemetry_off_and_no_otel_settings(
    environment, variables
) -> None:
    env = variables()
    assert env["APP_ENV"] == environment
    assert not [key for key in env if key.startswith("OTEL_")]  # nothing to add on merge
    result = subprocess.run(
        [sys.executable, "-c", STARTUP_CHECK, environment, SHA],
        cwd=BACKEND,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "ok"
    assert f"SpendWise API started: environment {environment}, version {SHA}, telemetry off" in (
        result.stderr
    )


@pytest.mark.parametrize("environment", ["development", "production"])
def test_turning_telemetry_on_without_a_ratio_stops_a_deployed_app(environment) -> None:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "APP_ENV": environment,
        "DATABASE_URL": "postgresql://spendwise:x@db.invalid/spendwise",
        "OTEL_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4318",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert f"APP_ENV={environment} with OTEL_ENABLED=true requires OTEL_TRACES_SAMPLE_RATIO" in (
        result.stderr
    )


def test_the_process_wide_setup_runs_once_and_shuts_down_cleanly() -> None:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "APP_ENV": "test",
        "FRONTEND_DIST": "",
        "AI_PROVIDER": "fake",
        "DATABASE_URL": "sqlite://",
        "OTEL_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{closed_port()}",
    }
    result = subprocess.run(
        [sys.executable, "-c", PROCESS_CHECK],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("ok"), result.stdout
    elapsed = float(result.stdout.split()[1].rstrip("s"))
    assert elapsed < 20
    # The app's own startup line, and no export error fed back into the app's log.
    assert "SpendWise API started: environment test" in result.stderr
    assert "Telemetry on: OTLP/HTTP to http://127.0.0.1:" in result.stderr
