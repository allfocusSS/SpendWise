"""End to end: SpendWise's metrics, logs and traces in Grafana's LGTM stack, and the dashboard.

The real image, PostgreSQL and grafana/otel-lgtm run in Compose (compose.dashboard.yaml). The
tests send real traffic, including controlled failures, then ask Grafana (the only published
port) what Prometheus, Loki and Tempo received, and check the provisioned dashboard's queries
against that data. Canary values (an email, a password, a description, an amount, a category
name, AI input text) are sent too, and must not appear in any metric label or dashboard value.

No HTTP endpoint calls AI parsing yet (Issue #2), so the AI traffic runs the real provider
factory and the real metered provider in a one-off process inside the app container
(integration/ai_traffic.py): nothing is added to the application for it.
"""

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from integration import ai_traffic
from integration.lgtm import Backends, wait_for
from integration.stack import Stack

DASHBOARD = (
    Path(__file__).resolve().parents[2]
    / "deploy/observability/grafana/dashboards/spendwise-overview.json"
)
SELECT = 'service_name="spendwise-api"'
SIGN_IN_REFUSED = "Sign-in refused: unknown email or wrong password"

# Distinctive canaries: none may reach a metric label, series metadata or the dashboard.
CANARY = secrets.token_hex(4)
CANARY_EMAIL = f"canary-{CANARY}@example.com"
CANARY_PASSWORD = f"Canary-Password-{CANARY}"
CANARY_DESCRIPTION = f"Canary rent to Askar {CANARY}"
CANARY_CATEGORY = f"Canary Category {CANARY}"
CANARY_MERCHANT = f"CanaryMerchant{CANARY}"
CANARY_AMOUNT = 987_654_321_07
CANARIES = (
    CANARY_EMAIL,
    CANARY_PASSWORD,
    CANARY_DESCRIPTION,
    CANARY_CATEGORY,
    CANARY_MERCHANT,
    str(CANARY_AMOUNT),
    CANARY,
)

CANARY_AI_TEXT = f"{CANARY_MERCHANT} taxi 2500 yesterday"

SAVED, REJECTED, REFUSED_SIGN_INS, AI_PARSES, AI_OUTAGES = 3, 1, 3, 5, 2


@pytest.fixture(scope="module")
def backends(grafana: httpx.Client) -> Backends:
    backends = Backends(grafana)  # Grafana and its data sources are ready (conftest.py)
    # The app's zero series (metrics.initialize) arrived: from here on every event is an increase.
    wait_for(
        "the app's first metrics in Prometheus",
        lambda: backends.query(f"spendwise_transaction_created_total{{{SELECT}}}"),
    )
    return backends


@dataclass
class Traffic:
    transaction_ids: list[int]


@pytest.fixture(scope="module")
def traffic(stack: Stack, backends: Backends) -> Traffic:
    with httpx.Client(base_url=stack.base_url, timeout=30) as client:
        for probe in ("/api/health", "/api/health/ready", "/api/meta"):
            assert client.get(probe).status_code == 200
        signup = client.post(
            "/api/auth/signup", json={"email": CANARY_EMAIL, "password": CANARY_PASSWORD}
        )
        assert signup.status_code == 201, signup.text
        category = client.post("/api/categories", json={"name": CANARY_CATEGORY, "type": "expense"})
        assert category.status_code == 201, category.text
        body = {
            "amount_cents": CANARY_AMOUNT,
            "type": "expense",
            "category_id": category.json()["id"],
            "description": CANARY_DESCRIPTION,
            "occurred_on": "2026-11-15",
        }
        ids = []
        for _ in range(SAVED):
            created = client.post("/api/transactions", json=body)
            assert created.status_code == 201, created.text
            ids.append(created.json()["id"])
        # Controlled failure: a category that doesn't exist (a validation error, never a 5xx).
        rejected = client.post("/api/transactions", json=body | {"category_id": 999_999_999})
        assert rejected.status_code == 422
        assert client.get(f"/api/transactions/{ids[0]}").status_code == 200
        assert client.get("/api/analytics/summary").status_code == 200
        for password in ("wrong-one", "wrong-two"):
            refused = client.post(
                "/api/auth/login", json={"email": CANARY_EMAIL, "password": password}
            )
            assert refused.status_code == 401
        unknown = client.post(
            "/api/auth/login", json={"email": f"nobody-{CANARY}@example.com", "password": "x"}
        )
        assert unknown.status_code == 401
    ai_traffic.send(
        stack,
        text=CANARY_AI_TEXT,
        category=CANARY_CATEGORY,
        parses=AI_PARSES,
        outages=AI_OUTAGES,
        outage_message="The AI provider is unavailable (smoke test)",
    )
    return Traffic(ids)


def total(backends: Backends, metric: str, matchers: str = "") -> float:
    labels = SELECT + (f", {matchers}" if matchers else "")
    return backends.value(f"sum({metric}{{{labels}}})") or 0.0


@pytest.fixture(scope="module")
def exported(backends: Backends, traffic: Traffic) -> Backends:
    """Waits until Prometheus has every count the traffic produced."""
    expected = expected_counts()

    def arrived() -> bool:
        return all(total(backends, *key) >= count for key, count in expected.items())

    wait_for("the business metrics in Prometheus", arrived)
    return backends


def expected_counts() -> dict[tuple[str, str], int]:
    return {
        ("spendwise_transaction_created_total", ""): SAVED,
        ("spendwise_transaction_create_error_total", 'error_type="validation"'): REJECTED,
        ("spendwise_auth_sign_in_failure_total", ""): REFUSED_SIGN_INS,
        ("spendwise_ai_parse_request_total", 'spendwise_ai_provider="fake"'): AI_PARSES
        + AI_OUTAGES,
        ("spendwise_ai_parse_error_total", 'error_type="provider"'): AI_OUTAGES,
        ("spendwise_ai_parse_duration_seconds_count", ""): AI_PARSES + AI_OUTAGES,
    }


# --- Metrics -----------------------------------------------------------------------------------


def test_business_metrics_reach_prometheus_counted_exactly_once(exported: Backends) -> None:
    # A fresh stack: the counters' values are exactly what was sent, no more (no double count).
    for (metric, matchers), count in expected_counts().items():
        assert total(exported, metric, matchers) == count, (metric, matchers)
    # Errors of other types stayed at zero, and successful parses recorded no error.
    assert (
        total(exported, "spendwise_transaction_create_error_total", 'error_type!="validation"') == 0
    )
    assert total(exported, "spendwise_ai_parse_error_total", 'error_type!="provider"') == 0
    assert (
        total(
            exported,
            "spendwise_transaction_created_total",
            'spendwise_transaction_type="expense", spendwise_transaction_source="manual"',
        )
        == SAVED
    )


def test_series_carry_only_bounded_labels(exported: Backends) -> None:
    series = exported.prometheus(
        "series", **{"match[]": f'{{__name__=~"spendwise_.*", {SELECT}}}'}
    )["data"]
    assert {s["__name__"] for s in series} >= {
        "spendwise_transaction_created_total",
        "spendwise_transaction_create_error_total",
        "spendwise_auth_sign_in_failure_total",
        "spendwise_ai_parse_request_total",
        "spendwise_ai_parse_error_total",
        "spendwise_ai_parse_duration_seconds_bucket",
    }
    resource_labels = {
        "__name__",
        "job",
        "instance",
        "service_name",
        "service_version",
        "service_instance_id",
        "deployment_environment_name",
    }
    metric_labels = {
        "spendwise_transaction_type",
        "spendwise_transaction_source",
        "spendwise_ai_provider",
        "error_type",
        "le",
    }
    for s in series:
        assert set(s) <= resource_labels | metric_labels, s
        assert s["deployment_environment_name"] == "local"
    # A handful of series per metric, whatever the traffic.
    assert len(series) < 80


def test_controlled_failures_move_the_dashboards_failure_panels(exported: Backends) -> None:
    def panel(title: str) -> float | None:
        (expr,) = [t["expr"] for p in panels() if p["title"] == title for t in p["targets"]]
        return exported.value(substitute(expr))

    assert panel("Failed saves") >= REJECTED
    assert 0 < panel("Save failure rate") <= 100
    assert panel("Parse failures") >= AI_OUTAGES
    assert 0 < panel("Parse success rate") < 100
    assert panel("Refused sign-ins") >= REFUSED_SIGN_INS
    assert panel("Transactions saved") >= SAVED


# --- The dashboard -----------------------------------------------------------------------------


def panels() -> list[dict]:
    return [p for p in json.loads(DASHBOARD.read_text())["panels"] if p["type"] != "row"]


def substitute(expr: str, version: str = ".*") -> str:
    for variable, value in (
        ("$__rate_interval", "5m"),  # covers the traffic, however long the tests took
        ("$__range", "15m"),
        ("$environment", "local"),
        ("$version", version),
    ):
        expr = expr.replace(variable, value)
    return expr


def test_the_dashboard_is_provisioned_from_git(grafana: httpx.Client, backends) -> None:
    answer = grafana.get("/api/dashboards/uid/spendwise-overview")
    assert answer.status_code == 200
    served = answer.json()
    assert served["dashboard"]["title"] == "SpendWise — Application Overview"
    assert served["meta"]["provisioned"] is True
    assert served["meta"]["folderTitle"] == "SpendWise"
    in_git = json.loads(DASHBOARD.read_text())
    assert [p["title"] for p in served["dashboard"]["panels"]] == [
        p["title"] for p in in_git["panels"]
    ]
    found = grafana.get("/api/search", params={"query": "SpendWise — Application Overview"}).json()
    assert [d["uid"] for d in found] == ["spendwise-overview"]


def test_every_dashboard_query_is_valid_and_the_core_panels_have_data(
    exported: Backends, stack: Stack
) -> None:
    core = {
        "Requests / s",
        "p95 latency",
        "Transactions saved",
        "Parse requests",
        "p95 parse time",
        "Refused sign-ins",
        "Running versions",
        "Request latency",
        "AI parse duration",
    }
    for panel in panels():
        for target in panel["targets"]:
            if panel["datasource"]["type"] == "loki":
                assert exported.loki(substitute(target["expr"])), panel["title"]
                continue
            # Valid PromQL against the real series, with the dashboard's variables filled in.
            result = exported.query(substitute(target["expr"], version=stack.app_version))
            if panel["title"] in core:
                assert result, panel["title"]
                assert any(v["value"][1] not in ("NaN", "0") for v in result), (
                    panel["title"],
                    result,
                )


def test_the_variables_offer_the_real_environment_and_version(
    exported: Backends, stack: Stack
) -> None:
    variables = {v["name"]: v for v in json.loads(DASHBOARD.read_text())["templating"]["list"]}
    for name, label, expected in (
        ("environment", "deployment_environment_name", "local"),
        ("version", "service_version", stack.app_version),
    ):
        selector = re.fullmatch(r"label_values\((.*), (\w+)\)", variables[name]["query"]["query"])
        assert selector and selector.group(2) == label
        match = selector.group(1).replace("$environment", ".*")
        values = {s.get(label) for s in exported.prometheus("series", **{"match[]": match})["data"]}
        assert expected in values, (name, values)
        assert not any(canary in repr(values) for canary in CANARIES)


# --- Logs and traces ---------------------------------------------------------------------------


def test_application_logs_reach_loki_with_their_resource(exported: Backends) -> None:
    streams = wait_for(
        "the refused sign-ins in Loki",
        lambda: exported.loki(
            f'{{{SELECT}, deployment_environment_name="local"}} |= "{SIGN_IN_REFUSED}"'
        ),
    )
    lines = [value for stream in streams for value in stream["values"]]
    assert len(lines) == REFUSED_SIGN_INS
    for stream in streams:
        assert stream["stream"]["service_name"] == "spendwise-api"
        assert re.fullmatch(r"[0-9a-f]{32}", stream["stream"]["trace_id"])


def test_server_spans_reach_tempo_and_link_to_the_logs(exported: Backends) -> None:
    query = (
        '{resource.service.name="spendwise-api" && resource.deployment.environment.name="local"'
        ' && name="POST /api/transactions"}'
    )
    found = wait_for(
        "the transaction spans in Tempo",
        lambda: exported.tempo("search", q=query, limit=20).json().get("traces"),
    )
    assert len(found) >= SAVED + REJECTED
    # The trace of a refused sign-in's log record is in Tempo too.
    (stream, *_) = exported.loki(f'{{{SELECT}}} |= "{SIGN_IN_REFUSED}"')
    trace_id = stream["stream"]["trace_id"]
    trace = exported.tempo(f"v2/traces/{trace_id}")
    assert trace.status_code == 200, trace.text
    assert "POST /api/auth/login" in trace.text


# --- Privacy and exposure ----------------------------------------------------------------------


def test_no_canary_in_any_metric_label_metadata_or_dashboard(exported: Backends, grafana) -> None:
    labels = exported.prometheus("labels")["data"]
    values = {label: exported.prometheus(f"label/{label}/values")["data"] for label in labels}
    metadata = exported.prometheus("metadata")["data"]
    served = grafana.get("/api/dashboards/uid/spendwise-overview").json()
    for name, text in (
        ("label names", repr(labels)),
        ("label values", repr(values)),
        ("metric metadata", repr(metadata)),
        ("dashboard", json.dumps(served)),
    ):
        for canary in CANARIES:
            assert canary not in text, (name, canary)
    # The canaries were sent: the AI process and the API did see them (sanity check).
    assert "spendwise_ai_parse_request_total" in values["__name__"]


def test_only_grafana_is_published_and_only_on_loopback(stack: Stack) -> None:
    published = {
        name: [(p["URL"], p["TargetPort"]) for p in service["Publishers"] if p.get("PublishedPort")]
        for name, service in stack.services().items()
    }
    # No OTLP, Prometheus, Loki, Tempo or alert receiver port; the app's is the local stack's own.
    assert {name: ports for name, ports in published.items() if ports} == {
        "app": [("127.0.0.1", 8000)],
        "lgtm": [("127.0.0.1", 3000)],
    }
