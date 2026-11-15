"""OpenTelemetry settings, resource, sampler and redaction (app/observability).

docs/observability.md describes the settings. Nothing here starts an exporter or a thread.
"""

import math

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.sampling import Decision
from opentelemetry.trace import NonRecordingSpan, SpanContext, Status, StatusCode, TraceFlags
from pydantic import ValidationError

from app.core.config import Settings
from app.observability import build_resource, setup_telemetry
from app.observability.privacy import HTTP_METRIC_ATTRIBUTES, redact
from app.observability.telemetry import EXCLUDED_URLS, build_sampler

SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
PG_URL = "postgresql+psycopg://spendwise:not-a-real-password@db.example:5432/spendwise"
ENDPOINT = "http://otel-collector:4318"
OTEL_VARS = (
    "OTEL_ENABLED",
    "OTEL_SDK_DISABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_TRACES_SAMPLE_RATIO",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_SERVICE_NAME",
    "APP_ENV",
    "APP_VERSION",
    "RENDER_GIT_COMMIT",
    "DATABASE_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in OTEL_VARS:
        monkeypatch.delenv(var, raising=False)


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def enabled(**values) -> Settings:
    return settings(**{"otel_enabled": True, "otel_exporter_otlp_endpoint": ENDPOINT, **values})


# --- On and off ------------------------------------------------------------------------------


def test_telemetry_is_off_unless_enabled() -> None:
    config = settings()
    assert config.otel_enabled is False
    assert config.telemetry_enabled is False


def test_otel_enabled_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", ENDPOINT)
    assert settings().telemetry_enabled is True


def test_the_standard_sdk_switch_turns_it_off(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert enabled().telemetry_enabled is False


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_a_malformed_switch_stops_startup(monkeypatch, value) -> None:
    monkeypatch.setenv("OTEL_ENABLED", value)
    with pytest.raises(ValidationError, match="otel_enabled"):
        settings()


# --- Endpoint and protocol -------------------------------------------------------------------


def test_enabled_needs_an_endpoint() -> None:
    with pytest.raises(ValidationError, match="requires OTEL_EXPORTER_OTLP_ENDPOINT"):
        settings(otel_enabled=True)


def test_disabled_needs_no_endpoint() -> None:
    assert settings(otel_enabled=False).otel_exporter_otlp_endpoint is None


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("http://otel-collector:4318", "http://otel-collector:4318"),
        ("http://otel-collector:4318/", "http://otel-collector:4318"),
        ("https://collector.internal:4318", "https://collector.internal:4318"),
        ("  http://127.0.0.1:4318  ", "http://127.0.0.1:4318"),
    ],
)
def test_the_endpoint_is_a_base_url(given, expected) -> None:
    assert enabled(otel_exporter_otlp_endpoint=given).otel_exporter_otlp_endpoint == expected


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("otel-collector:4318", "http:// or https:// URL"),
        ("ftp://otel-collector:4318", "http:// or https:// URL"),
        ("http://", "http:// or https:// URL"),
        ("http://otel-collector:99999", "http:// or https:// URL"),
        ("http://user:s3cret-pass@otel-collector:4318", "must not contain credentials"),
        ("http://otel-collector:4318?token=s3cret-pass", "query string or fragment"),
    ],
)
def test_a_malformed_endpoint_stops_startup(value, message) -> None:
    with pytest.raises(ValidationError, match=message) as error:
        enabled(otel_exporter_otlp_endpoint=value)
    assert "s3cret-pass" not in str(error.value)  # never echoed


def test_a_malformed_endpoint_stops_startup_even_while_disabled(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "not a url")
    with pytest.raises(ValidationError, match="otel_exporter_otlp_endpoint"):
        settings()


def test_only_otlp_http_protobuf_is_supported(monkeypatch) -> None:
    assert enabled().otel_exporter_otlp_protocol == "http/protobuf"
    for protocol in ("grpc", "http/json", "HTTP/PROTOBUF"):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", protocol)
        with pytest.raises(ValidationError, match="otel_exporter_otlp_protocol"):
            enabled()


# --- Sampling ratio --------------------------------------------------------------------------


@pytest.mark.parametrize("app_env", ["local", "test"])
def test_every_trace_is_kept_by_default_locally_and_in_tests(app_env) -> None:
    assert enabled(app_env=app_env).traces_sample_ratio == 1.0


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_deployed_environments_must_choose_a_ratio(app_env) -> None:
    with pytest.raises(ValidationError, match=f"APP_ENV={app_env} .* OTEL_TRACES_SAMPLE_RATIO"):
        enabled(app_env=app_env, database_url=PG_URL)
    config = enabled(app_env=app_env, database_url=PG_URL, otel_traces_sample_ratio=0.1)
    assert config.traces_sample_ratio == 0.1


# Development (Render) and production (AWS) run with telemetry off today, configured only by
# their environment variables. Turning it off must never need any other OTEL_* setting.


@pytest.mark.parametrize("app_env", ["development", "production"])
@pytest.mark.parametrize("switch", [None, "false", "0", "FALSE"])
def test_telemetry_off_needs_no_endpoint_and_no_ratio_when_deployed(monkeypatch, app_env, switch):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    if switch is not None:
        monkeypatch.setenv("OTEL_ENABLED", switch)
    config = settings()  # starts: no OTEL_TRACES_SAMPLE_RATIO, no OTEL_EXPORTER_OTLP_ENDPOINT
    assert config.telemetry_enabled is False
    assert config.otel_traces_sample_ratio is None
    assert config.otel_exporter_otlp_endpoint is None
    assert setup_telemetry(config) is None  # no providers, exporters or threads


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_the_sdk_switch_off_needs_no_ratio_when_deployed(monkeypatch, app_env) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert settings().telemetry_enabled is False


@pytest.mark.parametrize("app_env", ["development", "production"])
@pytest.mark.parametrize("ratio", [None, ""])
def test_telemetry_on_requires_a_ratio_when_deployed(monkeypatch, app_env, ratio) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", ENDPOINT)
    if ratio is not None:
        monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", ratio)  # empty counts as unset
    with pytest.raises(ValidationError, match=f"APP_ENV={app_env} .* OTEL_TRACES_SAMPLE_RATIO"):
        settings()


@pytest.mark.parametrize("app_env", ["development", "production"])
@pytest.mark.parametrize(
    ("ratio", "expected"), [("0.1", 0.1), ("0", 0.0), ("0.0", 0.0), ("1", 1.0)]
)
def test_telemetry_on_accepts_a_valid_ratio_when_deployed(monkeypatch, app_env, ratio, expected):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", ratio)
    config = settings()
    assert config.telemetry_enabled is True
    assert config.traces_sample_ratio == expected


@pytest.mark.parametrize("app_env", ["development", "production"])
@pytest.mark.parametrize(
    "ratio", ["nan", "NaN", "inf", "-inf", "10%", "0.1%", "1.5", "-0.1", "one", "0.1 0.2"]
)
def test_telemetry_on_refuses_an_invalid_ratio_when_deployed(monkeypatch, app_env, ratio) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", ratio)
    with pytest.raises(ValidationError, match="otel_traces_sample_ratio"):
        settings()


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_telemetry_on_requires_an_endpoint_when_deployed(monkeypatch, app_env) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", "0.1")
    with pytest.raises(ValidationError, match="requires OTEL_EXPORTER_OTLP_ENDPOINT"):
        settings()


@pytest.mark.parametrize("value", ["0", "0.0", "0.25", "1", "1.0"])
def test_ratios_from_zero_to_one_are_accepted(monkeypatch, value) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", value)
    assert enabled().traces_sample_ratio == float(value)


@pytest.mark.parametrize("value", ["-0.1", "1.01", "2", "nan", "inf", "-inf", "ten percent", "10%"])
def test_other_ratios_stop_startup(monkeypatch, value) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", value)
    with pytest.raises(ValidationError, match="otel_traces_sample_ratio"):
        enabled()


def test_an_empty_ratio_is_unset(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLE_RATIO", "")
    assert enabled().otel_traces_sample_ratio is None


# --- Resource --------------------------------------------------------------------------------


def test_the_resource_names_the_service_its_version_and_environment() -> None:
    resource = build_resource(enabled(app_env="local", app_version=SHA))
    attributes = resource.attributes
    assert attributes["service.name"] == "spendwise-api"
    assert attributes["service.version"] == SHA
    assert attributes["deployment.environment.name"] == "local"
    assert "deployment.environment" not in attributes
    assert attributes["telemetry.sdk.language"] == "python"


def test_the_resource_has_no_version_when_none_is_known() -> None:
    assert "service.version" not in build_resource(enabled()).attributes


def test_environment_variables_add_to_the_resource_but_never_replace_it(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "something-else")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.name=other,deployment.environment.name=production,cloud.region=eu-central-1",
    )
    attributes = build_resource(enabled(app_env="local")).attributes
    assert attributes["service.name"] == "spendwise-api"
    assert attributes["deployment.environment.name"] == "local"
    assert attributes["cloud.region"] == "eu-central-1"


# --- Sampler ---------------------------------------------------------------------------------

TRACE_ID = 0x0AF7651916CD43DD8448EB211C80319C


def parent(sampled: bool, remote: bool):
    context = SpanContext(
        trace_id=TRACE_ID,
        span_id=0x00F067AA0BA902B7,
        is_remote=remote,
        trace_flags=TraceFlags(TraceFlags.SAMPLED if sampled else TraceFlags.DEFAULT),
    )
    return trace.set_span_in_context(NonRecordingSpan(context))


def decision(ratio: float, parent_context=None) -> Decision:
    return build_sampler(ratio).should_sample(parent_context, TRACE_ID, "GET /api/x").decision


def test_new_traces_are_sampled_by_ratio() -> None:
    assert decision(1.0) == Decision.RECORD_AND_SAMPLE
    assert decision(0.0) == Decision.DROP


def test_spans_inside_a_sampled_request_follow_it() -> None:
    assert decision(0.0, parent(sampled=True, remote=False)) == Decision.RECORD_AND_SAMPLE
    assert decision(1.0, parent(sampled=False, remote=False)) == Decision.DROP


def test_a_client_traceparent_cannot_decide_sampling() -> None:
    # A caller can send any traceparent header; the ratio decides, not its sampled flag.
    assert decision(0.0, parent(sampled=True, remote=True)) == Decision.DROP
    assert decision(1.0, parent(sampled=False, remote=True)) == Decision.RECORD_AND_SAMPLE


def test_the_sampler_describes_itself() -> None:
    assert "TraceIdRatioBased{0.25}" in build_sampler(0.25).get_description()
    assert math.isclose(enabled(otel_traces_sample_ratio=0.25).traces_sample_ratio, 0.25)


# --- Redaction and exclusions ----------------------------------------------------------------


def span(attributes: dict) -> ReadableSpan:
    return ReadableSpan(name="GET /api/transactions", attributes=attributes)


def test_redaction_drops_people_headers_and_query_strings() -> None:
    redacted = redact(
        span(
            {
                "http.request.method": "GET",
                "http.route": "/api/transactions",
                "url.path": "/api/transactions",
                "url.query": "note=rent",
                "client.address": "203.0.113.7",
                "client.port": 51234,
                "user_agent.original": "Mozilla/5.0",
                "http.request.header.authorization": ("Bearer eyJ.secret",),
                "http.request.header.cookie": ("spendwise_session=abc",),
                "http.response.header.set_cookie": ("spendwise_session=def",),
                "http.url": "http://host/api/transactions?note=rent",
                "net.peer.ip": "203.0.113.7",
            }
        )
    )
    assert dict(redacted.attributes) == {
        "http.request.method": "GET",
        "http.route": "/api/transactions",
        "url.path": "/api/transactions",
    }
    assert redacted.name == "GET /api/transactions"


def test_exceptions_keep_their_type_but_not_their_message_or_stack_trace() -> None:
    secret = "Key (user_id, name, type)=(1, Rent to Askar, expense) already exists"
    failed = ReadableSpan(
        name="POST /api/categories",
        attributes={"http.route": "/api/categories", "error.type": "500"},
        events=[
            Event(
                "exception",
                {
                    "exception.type": "sqlalchemy.exc.IntegrityError",
                    "exception.message": f"duplicate key value\nDETAIL:  {secret}",
                    "exception.stacktrace": f"Traceback ...\nIntegrityError: {secret}",
                    "exception.escaped": "False",
                },
                timestamp=123,
            ),
            Event("retry", {"attempt": 2}, timestamp=124),
        ],
        status=Status(StatusCode.ERROR, f"IntegrityError: {secret}"),
    )
    redacted = redact(failed)
    exception, retry = redacted.events
    assert dict(exception.attributes) == {
        "exception.type": "sqlalchemy.exc.IntegrityError",
        "exception.escaped": "False",
    }
    assert (exception.name, exception.timestamp) == ("exception", 123)
    assert retry is failed.events[1]  # other events are left alone
    assert redacted.status.status_code is StatusCode.ERROR
    assert redacted.status.description is None
    assert dict(redacted.attributes) == {"http.route": "/api/categories", "error.type": "500"}
    assert secret not in redacted.to_json()


def test_redaction_keeps_a_clean_span_as_it_is() -> None:
    clean = span({"http.route": "/api/categories"})
    assert redact(clean) is clean


def test_http_metric_attributes_are_bounded() -> None:
    assert {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "error.type",
        "url.scheme",
        "network.protocol.name",
        "network.protocol.version",
    } == HTTP_METRIC_ATTRIBUTES
    for unbounded in ("url.path", "url.full", "url.query", "server.address", "client.address"):
        assert unbounded not in HTTP_METRIC_ATTRIBUTES


def test_only_the_probe_paths_are_excluded() -> None:
    import re

    patterns = [re.compile(p) for p in EXCLUDED_URLS.split(",")]

    def excluded(url: str) -> bool:
        return any(p.search(url) for p in patterns)

    for url in (
        "http://localhost:8000/api/health",
        "https://54.79.77.189.nip.io/api/health/ready",
        "http://testserver/api/meta",
    ):
        assert excluded(url), url
    for url in (
        "http://testserver/api/healthz",
        "http://testserver/api/health/ready/x",
        "http://testserver/api/transactions",
        "http://testserver/api/meta/x",
        "http://testserver/x/api/health/extra",
        "http://evil/api/health/api/transactions",
    ):
        assert not excluded(url), url
