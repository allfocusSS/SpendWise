"""The SpendWise dashboard (deploy/observability/grafana/) and its local LGTM stack, as data.

The dashboard smoke test (dashboard_smoke/, CI job "Observability Dashboard") runs them against
real data; these check the rules every query and setting must follow.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
GRAFANA = ROOT / "deploy" / "observability" / "grafana"
DASHBOARD = GRAFANA / "dashboards" / "spendwise-overview.json"
OVERLAY = ROOT / "compose.dashboard.yaml"
SELECTOR = (
    'service_name="spendwise-api", deployment_environment_name=~"$environment", '
    'service_version=~"$version"'
)
# Metric labels a query may group or filter by: all bounded (docs/observability.md).
BOUNDED_LABELS = {
    "le",
    "error_type",
    "http_response_status_code",
    "spendwise_transaction_type",
    "spendwise_transaction_source",
    "deployment_environment_name",
    "service_version",
    "status_class",
}


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return json.loads(DASHBOARD.read_text())


def panels(dashboard: dict) -> list[dict]:
    return [p for p in dashboard["panels"] if p["type"] != "row"]


def prometheus_targets(dashboard: dict) -> list[tuple[str, str]]:
    return [
        (panel["title"], target["expr"])
        for panel in panels(dashboard)
        if panel["datasource"]["type"] == "prometheus"
        for target in panel["targets"]
    ]


def test_identity(dashboard) -> None:
    assert dashboard["uid"] == "spendwise-overview"
    assert dashboard["title"] == "SpendWise — Application Overview"
    assert dashboard["editable"] is False  # changed in Git, not in the UI
    assert "spendwise" in dashboard["tags"]


def test_sections_and_panels(dashboard) -> None:
    rows = [p["title"] for p in dashboard["panels"] if p["type"] == "row"]
    assert rows == [
        "Service health",
        "Transactions",
        "AI transaction parsing",
        "Authentication",
        "Runtime",
    ]
    titles = {p["title"] for p in panels(dashboard)}
    assert {
        "Requests / s",
        "Server errors (5xx)",
        "p95 latency",
        "Active requests",
        "Transactions saved",
        "Failed saves",
        "Save failure rate",
        "Parse requests",
        "Parse failures",
        "Parse success rate",
        "p95 parse time",
        "AI parse duration",
        "Refused sign-ins",
        "Running versions",
        "Recent application logs",
    } <= titles
    for panel in panels(dashboard):
        assert panel.get("description"), panel["title"]  # every panel says what it shows
        assert panel["targets"], panel["title"]  # and queries live data: no fixed values


def test_panels_never_overlap(dashboard) -> None:
    cells: set[tuple[int, int]] = set()
    for panel in dashboard["panels"]:
        g = panel["gridPos"]
        assert g["x"] + g["w"] <= 24, panel["title"]
        mine = {
            (x, y) for x in range(g["x"], g["x"] + g["w"]) for y in range(g["y"], g["y"] + g["h"])
        }
        assert not cells & mine, panel["title"]
        cells |= mine


def test_variables_are_the_environment_and_version_only(dashboard) -> None:
    variables = {v["name"]: v for v in dashboard["templating"]["list"]}
    assert set(variables) == {"datasource", "environment", "version"}
    assert variables["environment"]["query"]["query"] == (
        'label_values(target_info{service_name="spendwise-api"}, deployment_environment_name)'
    )
    assert variables["version"]["query"]["query"].endswith(", service_version)")
    # "All" must match a process without a version too (no APP_VERSION locally).
    assert variables["version"]["allValue"] == ".*"


def test_every_prometheus_query_uses_the_data_source_and_the_variables(dashboard) -> None:
    for panel in panels(dashboard):
        if panel["datasource"]["type"] == "prometheus":
            assert panel["datasource"]["uid"] == "${datasource}", panel["title"]
    for title, expr in prometheus_targets(dashboard):
        selectors = re.findall(r"(?<!\$)\{([^{}]*)\}", expr)  # not label_replace's ${1}
        assert selectors, title
        for selector in selectors:
            assert selector.startswith(SELECTOR), (title, selector)


def test_counters_are_only_read_through_rate_or_increase(dashboard) -> None:
    for title, expr in prometheus_targets(dashboard):
        for counter in re.findall(r"(\w+_(?:total|count|bucket))\{", expr):
            assert re.search(rf"(rate|increase)\({counter}\{{", expr), (title, counter)


def test_histograms_are_aggregated_by_bucket(dashboard) -> None:
    for title, expr in prometheus_targets(dashboard):
        if "histogram_quantile" in expr:
            assert "sum by (le) (" in expr and "_bucket{" in expr, title


def test_ratios_never_divide_by_zero(dashboard) -> None:
    for title, expr in prometheus_targets(dashboard):
        if " / " in expr:
            denominator = expr.split(" / ", 1)[1]
            assert re.search(r"> 0\)+$", denominator.strip()), (title, denominator)


def test_queries_group_and_filter_by_bounded_labels_only(dashboard) -> None:
    for title, expr in prometheus_targets(dashboard):
        for group in re.findall(r"by \(([^)]*)\)", expr):
            assert {label.strip() for label in group.split(",")} <= BOUNDED_LABELS, (title, group)
        for label in re.findall(r"(\w+)=~?\"", expr):
            assert label in BOUNDED_LABELS | {"service_name"}, (title, label)


def test_the_logs_panel_reads_spendwise_logs_from_loki(dashboard) -> None:
    (logs,) = [p for p in panels(dashboard) if p["type"] == "logs"]
    assert logs["datasource"] == {"type": "loki", "uid": "loki"}
    assert logs["targets"][0]["expr"].startswith('{service_name="spendwise-api"')


def test_links_lead_to_spendwise_traces_and_logs(dashboard) -> None:
    links = {link["title"]: link["url"] for link in dashboard["links"]}
    assert set(links) == {"Traces (Tempo)", "Logs (Loki)"}
    assert all(url.startswith("/explore?") for url in links.values())  # Grafana's own pages


# --- Provisioning and the LGTM stack -------------------------------------------------------


@pytest.fixture(scope="module")
def overlay() -> dict[str, Any]:
    return yaml.safe_load(OVERLAY.read_text())


def test_the_dashboard_is_provisioned_from_git(overlay) -> None:
    provider = yaml.safe_load((GRAFANA / "dashboards.yaml").read_text())["providers"][0]
    folder = "/otel-lgtm/grafana/conf/provisioning/dashboards/custom"
    assert provider["options"]["path"] == folder
    assert provider["allowUiUpdates"] is False
    assert overlay["services"]["lgtm"]["volumes"][:2] == [
        "./deploy/observability/grafana/dashboards.yaml:/otel-lgtm/grafana/conf/provisioning/dashboards/custom.yaml:ro",
        f"./deploy/observability/grafana/dashboards:{folder}:ro",
    ]
    # The rest is the alerting provisioning (tests/unit/test_alerting_config.py), also read-only.
    assert all(v.endswith(":ro") for v in overlay["services"]["lgtm"]["volumes"])
    home = overlay["services"]["lgtm"]["environment"]["GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"]
    assert home == f"{folder}/{DASHBOARD.name}"


def test_the_lgtm_image_is_official_and_pinned(overlay) -> None:
    image = overlay["services"]["lgtm"]["image"]
    assert re.fullmatch(r"grafana/otel-lgtm:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", image), image


def test_only_grafana_is_published_and_only_on_loopback(overlay) -> None:
    lgtm = overlay["services"]["lgtm"]
    assert lgtm["ports"] == ["127.0.0.1:${GRAFANA_PORT:-3000}:3000"]
    assert "ports" not in overlay["services"]["app"]
    for forbidden in ("privileged", "network_mode", "cap_add", "pid", "devices"):
        assert forbidden not in lgtm, forbidden
    assert lgtm["security_opt"] == ["no-new-privileges:true"]
    assert lgtm["environment"]["ENABLE_OBI"] == "false"  # no eBPF: the app is instrumented
    assert lgtm["environment"]["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    # Only the pinned image's plugins: nothing downloaded or swapped in after start-up.
    assert lgtm["environment"]["GF_PLUGINS_PREINSTALL_DISABLED"] == "true"
    # Never on the database's network; "alerting" reaches the alert receiver only.
    assert lgtm["networks"] == ["dashboard", "alerting"]
    for name, service in overlay["services"].items():
        assert name == "lgtm" or "ports" not in service, name


def test_the_stack_has_a_health_check_and_sends_to_lgtm(overlay) -> None:
    assert overlay["services"]["lgtm"]["healthcheck"]["test"] == [
        "CMD",
        "/otel-lgtm/docker/healthcheck.sh",
    ]
    app = overlay["services"]["app"]["environment"]
    assert app["OTEL_ENABLED"] == "true"
    assert app["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://lgtm:4318"
    assert overlay["services"]["app"]["depends_on"] == {"lgtm": {"condition": "service_started"}}
    # Prometheus counts a counter's first increase from its OTLP start time.
    assert (
        "created-timestamp-zero-ingestion"
        in overlay["services"]["lgtm"]["environment"]["PROMETHEUS_EXTRA_ARGS"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "compose.yaml",
        "deploy/aws/compose.aws.yaml",
        "deploy/aws/spendwise-stack.yaml",
        "render.yaml",
        "Dockerfile",
        ".github/workflows/promote-production.yml",
    ],
)
def test_lgtm_is_never_part_of_a_deployment(path) -> None:
    text = (ROOT / path).read_text()
    assert "otel-lgtm" not in text and "grafana" not in text.lower(), path
