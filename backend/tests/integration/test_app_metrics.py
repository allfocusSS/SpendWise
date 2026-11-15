"""SpendWise's own metrics (app/observability/metrics.py), read from an in-memory MeterProvider.

Real API requests (transactions, sign-in) and the real AI provider factory, so each test shows
what the dashboard will count, and that it counts it exactly once, with bounded attributes only.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from app.ai import AIUnavailableError, build_ai_provider
from app.ai.metered import MeteredAIProvider
from app.ai.schemas import CategoryOption, TransactionDraftRequest
from app.core.config import Settings
from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Transaction
from app.observability import build_telemetry
from app.observability import metrics as app_metrics
from app.observability.privacy import APPLICATION_METRIC_ATTRIBUTES
from tests.conftest import ALICE, PASSWORD

CANARY_DESCRIPTION = "Canary rent to Askar Nurlanovich"
CANARY_AMOUNT = 123_456_789
TRANSACTION_METRICS = ("spendwise.transaction.created", "spendwise.transaction.create.error")


@dataclass
class Recorded:
    reader: InMemoryMetricReader

    def points(self, name: str) -> list:
        data = self.reader.get_metrics_data()
        return [
            point
            for resource_metrics in (data.resource_metrics if data else [])
            for scope in resource_metrics.scope_metrics
            for metric in scope.metrics
            if metric.name == name
            for point in metric.data.data_points
        ]

    def counts(self, name: str) -> dict[tuple, int]:
        """Counter value per attribute set (as sorted key/value tuples)."""
        return {tuple(sorted(p.attributes.items())): p.value for p in self.points(name)}

    def total(self, name: str) -> int:
        return sum(self.counts(name).values())

    def all_spendwise_points(self) -> list[tuple[str, dict]]:
        data = self.reader.get_metrics_data()
        return [
            (metric.name, dict(point.attributes))
            for resource_metrics in (data.resource_metrics if data else [])
            for scope in resource_metrics.scope_metrics
            for metric in scope.metrics
            if metric.name.startswith("spendwise.")
            for point in metric.data.data_points
        ]


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorded]:
    """The application metrics bound to an in-memory MeterProvider (telemetry on, no network)."""
    reader = InMemoryMetricReader()
    telemetry = build_telemetry(
        Settings(
            _env_file=None,
            otel_enabled=True,
            otel_exporter_otlp_endpoint="http://otel-collector.invalid:4318",
        ),
        span_exporter=InMemorySpanExporter(),
        metric_readers=[reader],
        log_exporter=InMemoryLogRecordExporter(),
    )
    # The process's instruments are put back afterwards.
    monkeypatch.setattr(app_metrics, "_instruments", app_metrics._instruments)
    app_metrics.bind(telemetry.meter_provider.get_meter("app.observability.metrics"))
    yield Recorded(reader)
    telemetry.shutdown()


def signed_in(app: FastAPI) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/auth/signup", json={"email": ALICE, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return client


def new_transaction(client: TestClient, **overrides) -> dict:
    category = next(c for c in client.get("/api/categories").json() if c["type"] == "expense")
    body = {
        "amount_cents": CANARY_AMOUNT,
        "type": "expense",
        "category_id": category["id"],
        "description": CANARY_DESCRIPTION,
        "occurred_on": "2026-11-15",
    }
    return body | overrides


# --- Transactions ----------------------------------------------------------------------------


def test_a_saved_transaction_counts_once(app, recorded) -> None:
    client = signed_in(app)
    assert client.post("/api/transactions", json=new_transaction(client)).status_code == 201

    assert recorded.counts("spendwise.transaction.created") == {
        (("spendwise.transaction.source", "manual"), ("spendwise.transaction.type", "expense")): 1
    }
    assert recorded.total("spendwise.transaction.create.error") == 0


def test_every_saved_transaction_counts_exactly_once(app, recorded) -> None:
    client = signed_in(app)
    for _ in range(3):
        assert client.post("/api/transactions", json=new_transaction(client)).status_code == 201
    income = next(c for c in client.get("/api/categories").json() if c["type"] == "income")
    body = new_transaction(client, type="income", category_id=income["id"], source="ai")
    assert client.post("/api/transactions", json=body).status_code == 201
    # Reading, updating and deleting transactions are not creations.
    created = client.get("/api/transactions").json()["items"][0]
    client.put(f"/api/transactions/{created['id']}", json=new_transaction(client))
    client.delete(f"/api/transactions/{created['id']}")

    assert recorded.counts("spendwise.transaction.created") == {
        (("spendwise.transaction.source", "manual"), ("spendwise.transaction.type", "expense")): 3,
        (("spendwise.transaction.source", "ai"), ("spendwise.transaction.type", "income")): 1,
    }
    assert recorded.total("spendwise.transaction.create.error") == 0


def test_a_rejected_transaction_counts_one_validation_error(app, recorded) -> None:
    client = signed_in(app)
    response = client.post("/api/transactions", json=new_transaction(client, category_id=999999))
    assert response.status_code == 422

    assert recorded.counts("spendwise.transaction.create.error") == {
        (("error.type", "validation"),): 1
    }
    assert recorded.total("spendwise.transaction.created") == 0


def test_a_malformed_request_is_not_a_creation_attempt(app, recorded) -> None:
    # FastAPI refuses it before the service runs: no transaction was ever being created.
    client = signed_in(app)
    assert client.post("/api/transactions", json={"amount_cents": "lots"}).status_code == 422
    for name in TRANSACTION_METRICS:
        assert recorded.total(name) == 0


def test_a_database_failure_counts_one_database_error(app, recorded, engine: Engine) -> None:
    client = signed_in(app)
    body = new_transaction(client)
    Transaction.__table__.drop(engine)  # this test's own database: the INSERT then fails
    response = client.post("/api/transactions", json=body)
    assert response.status_code == 500

    assert recorded.counts("spendwise.transaction.create.error") == {
        (("error.type", "database"),): 1
    }
    assert recorded.total("spendwise.transaction.created") == 0


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (BusinessRuleError("Category 7 does not exist"), "validation"),
        (NotFoundError("Transaction not found"), "validation"),
        (AIUnavailableError("down"), "provider"),
        (IntegrityError("INSERT …", {}, Exception("duplicate")), "database"),
        (OperationalError("SELECT 1", {}, Exception("connection lost")), "database"),
        (KeyError("a bug"), "internal"),
        (RuntimeError(CANARY_DESCRIPTION), "internal"),
    ],
)
def test_errors_fall_into_a_fixed_set_of_types(recorded, error, expected) -> None:
    with (
        pytest.raises(type(error)) as raised,
        app_metrics.creating_transaction("expense", "manual"),
    ):
        raise error
    assert raised.value is error  # re-raised unchanged
    assert recorded.counts("spendwise.transaction.create.error") == {(("error.type", expected),): 1}


# --- Sign-in ---------------------------------------------------------------------------------


def test_each_refused_sign_in_counts_once_without_saying_why(app, recorded) -> None:
    client = signed_in(app)
    assert (
        client.post("/api/auth/login", json={"email": ALICE, "password": "wrong"}).status_code
        == 401
    )
    unknown = {"email": "nobody@example.com", "password": PASSWORD}
    assert client.post("/api/auth/login", json=unknown).status_code == 401

    # Wrong password and unknown email are the same count: no attribute tells them apart.
    assert recorded.counts("spendwise.auth.sign_in.failure") == {(): 2}


def test_a_successful_sign_in_is_not_a_failure(app, recorded) -> None:
    client = signed_in(app)
    assert (
        client.post("/api/auth/login", json={"email": ALICE, "password": PASSWORD}).status_code
        == 200
    )
    assert recorded.total("spendwise.auth.sign_in.failure") == 0


# --- AI parsing ------------------------------------------------------------------------------


def draft_request(text: str = "taxi 2500 yesterday") -> TransactionDraftRequest:
    return TransactionDraftRequest(
        text=text,
        categories=[CategoryOption(id=1, name="Transport", type="expense")],
        today=date(2026, 11, 15),
    )


def duration_points(recorded: Recorded) -> dict[tuple, tuple[int, float]]:
    return {
        tuple(sorted(p.attributes.items())): (p.count, p.sum)
        for p in recorded.points("spendwise.ai.parse.duration")
    }


def test_a_parse_through_the_real_factory_is_counted_and_timed(recorded, monkeypatch) -> None:
    provider = build_ai_provider(Settings(_env_file=None, ai_provider="fake"))
    clock = iter([100.0, 100.25])  # the monotonic clock, at the start and at the end
    monkeypatch.setattr(app_metrics.time, "monotonic", lambda: next(clock))

    draft = provider.parse_transaction(draft_request())

    assert draft.amount_text == "2500"  # the provider's own answer, unchanged
    assert recorded.counts("spendwise.ai.parse.request") == {
        (("spendwise.ai.provider", "fake"),): 1
    }
    assert duration_points(recorded) == {(("spendwise.ai.provider", "fake"),): (1, 0.25)}
    assert recorded.total("spendwise.ai.parse.error") == 0


class FailingProvider:
    def __init__(self, error: Exception, name: str = "anthropic") -> None:
        self.error, self.name = error, name

    def parse_transaction(self, request):
        raise self.error

    def generate_insights(self, request):
        raise self.error


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (AIUnavailableError("The provider is down"), "provider"),
        (TimeoutError("read timed out"), "provider"),
        (ValueError("model returned garbage"), "provider"),
        (BusinessRuleError("Text is empty"), "validation"),
    ],
)
def test_a_failed_parse_counts_one_error_and_its_duration(recorded, error, error_type) -> None:
    provider = MeteredAIProvider(FailingProvider(error))
    with pytest.raises(type(error)):
        provider.parse_transaction(draft_request())

    failed = (("error.type", error_type), ("spendwise.ai.provider", "anthropic"))
    assert recorded.counts("spendwise.ai.parse.request") == {
        (("spendwise.ai.provider", "anthropic"),): 1
    }
    assert recorded.counts("spendwise.ai.parse.error") == {failed: 1}
    ((key, (count, seconds)),) = duration_points(recorded).items()
    assert key == failed and count == 1 and seconds >= 0


def test_an_unknown_provider_is_never_named(recorded) -> None:
    provider = MeteredAIProvider(FailingProvider(ValueError("x"), name="my-own-llm-v7"))
    with pytest.raises(ValueError):
        provider.parse_transaction(draft_request())
    assert recorded.counts("spendwise.ai.parse.request") == {
        (("spendwise.ai.provider", "other"),): 1
    }


def test_insights_are_passed_through_and_not_counted_as_parsing(recorded) -> None:
    class InsightsOnly:
        name = "fake"
        insights = object()

        def parse_transaction(self, request):
            raise AssertionError("not called")

        def generate_insights(self, request):
            return self.insights

    inner = InsightsOnly()
    assert MeteredAIProvider(inner).generate_insights(object()) is inner.insights
    assert recorded.total("spendwise.ai.parse.request") == 0


# --- Zero series ---------------------------------------------------------------------------


def test_initialize_starts_every_known_series_at_zero(recorded) -> None:
    app_metrics.initialize("fake")
    assert recorded.counts("spendwise.transaction.created") == {
        (("spendwise.transaction.source", source), ("spendwise.transaction.type", type_)): 0
        for source in ("manual", "ai")
        for type_ in ("income", "expense")
    }
    assert recorded.counts("spendwise.transaction.create.error") == {
        (("error.type", error),): 0 for error in ("validation", "database", "internal")
    }
    assert recorded.counts("spendwise.auth.sign_in.failure") == {(): 0}
    assert recorded.counts("spendwise.ai.parse.request") == {
        (("spendwise.ai.provider", "fake"),): 0
    }
    assert recorded.counts("spendwise.ai.parse.error") == {
        (("error.type", error), ("spendwise.ai.provider", "fake")): 0
        for error in ("provider", "validation")
    }
    # Eleven series in all (4 + 3 + 1 + 1 + 2), however much traffic follows; events still count
    # from zero.
    assert len(recorded.all_spendwise_points()) == 11
    app_metrics.sign_in_failed()
    assert recorded.counts("spendwise.auth.sign_in.failure") == {(): 1}


def test_initialize_names_only_the_configured_provider(recorded) -> None:
    app_metrics.initialize("anthropic")
    assert recorded.counts("spendwise.ai.parse.request") == {
        (("spendwise.ai.provider", "anthropic"),): 0
    }


def test_the_app_initializes_its_series_when_telemetry_starts() -> None:
    from app import main

    source = Path(main.__file__).read_text()
    assert "app_metrics.initialize(settings.ai_provider)" in source
    assert source.index("instrument_app(app, telemetry)") < source.index("app_metrics.initialize")


# --- Cardinality and privacy -----------------------------------------------------------------


def test_attributes_are_bounded_and_hold_no_user_data(app, recorded) -> None:
    client = signed_in(app)
    client.post("/api/transactions", json=new_transaction(client))
    client.post("/api/transactions", json=new_transaction(client, category_id=424242))
    client.post("/api/auth/login", json={"email": ALICE, "password": "wrong"})
    build_ai_provider(Settings(_env_file=None, ai_provider="fake")).parse_transaction(
        draft_request(f"{CANARY_DESCRIPTION} 2500")
    )

    points = recorded.all_spendwise_points()
    assert {name for name, _ in points} == {
        "spendwise.transaction.created",
        "spendwise.transaction.create.error",
        "spendwise.auth.sign_in.failure",
        "spendwise.ai.parse.request",
        "spendwise.ai.parse.duration",
    }
    allowed_values = {
        "spendwise.transaction.type": {"income", "expense"},
        "spendwise.transaction.source": {"manual", "ai"},
        "spendwise.ai.provider": {"fake", "anthropic", "other"},
        "error.type": {"validation", "provider", "database", "internal"},
    }
    for name, attributes in points:
        assert set(attributes) <= APPLICATION_METRIC_ATTRIBUTES, (name, attributes)
        for key, value in attributes.items():
            assert value in allowed_values[key], (name, key, value)
    text = repr(points)
    for canary in (ALICE, PASSWORD, CANARY_DESCRIPTION, str(CANARY_AMOUNT), "424242", "Groceries"):
        assert canary not in text


def test_a_view_drops_any_other_attribute_key(recorded) -> None:
    # Even if code passed one by mistake, an unknown key never reaches an exported data point.
    app_metrics._instruments.transaction_created.add(
        1, {"spendwise.transaction.type": "expense", "user.id": "42", "email": ALICE}
    )
    assert recorded.counts("spendwise.transaction.created") == {
        (("spendwise.transaction.type", "expense"),): 1
    }


def test_the_attribute_keys_are_the_privacy_allowlist() -> None:
    assert {
        app_metrics.TRANSACTION_TYPE,
        app_metrics.TRANSACTION_SOURCE,
        app_metrics.AI_PROVIDER,
        app_metrics.ERROR_TYPE,
    } == APPLICATION_METRIC_ATTRIBUTES


# --- Telemetry off ---------------------------------------------------------------------------


def test_with_telemetry_off_recording_is_a_no_op(app) -> None:
    # No MeterProvider in the test process: the instruments do nothing, and the app behaves the
    # same (the whole API suite runs this way).
    client = signed_in(app)
    assert client.post("/api/transactions", json=new_transaction(client)).status_code == 201
    assert client.post("/api/auth/login", json={"email": ALICE, "password": "x"}).status_code == 401
    error = RuntimeError("still raised")
    with (
        pytest.raises(RuntimeError) as raised,
        app_metrics.creating_transaction("expense", "manual"),
    ):
        raise error
    assert raised.value is error
    app_metrics.sign_in_failed()
