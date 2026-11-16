"""SpendWise's alerting as code (deploy/observability/grafana/alerting/), as data.

The alert smoke test (alerts_smoke/, CI job "Observability Alerts") runs these files in Grafana
against real data; these check the rules every rule, the contact point, the notification policy
and the receiver's container must follow.
"""

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
ALERTING = ROOT / "deploy" / "observability" / "grafana" / "alerting"
DASHBOARD = ROOT / "deploy" / "observability" / "grafana" / "dashboards" / "spendwise-overview.json"
OVERLAY = ROOT / "compose.dashboard.yaml"

# uid: (title, severity, category, threshold, pending period)
EXPECTED = {
    "spendwise-http-5xx-rate": ("SpendWise HTTP 5xx Rate High", "critical", "http", 0.05, "1m"),
    "spendwise-http-p95-latency": ("SpendWise HTTP P95 Latency High", "warning", "http", 1, "1m"),
    "spendwise-transaction-save-failures": (
        "SpendWise Transaction Save Failure Rate High",
        "critical",
        "transaction",
        0.01,
        "1m",
    ),
    "spendwise-ai-parse-failures": (
        "SpendWise AI Parse Failure Rate High",
        "warning",
        "ai",
        0.1,
        "30s",
    ),
    "spendwise-sign-in-failures": ("SpendWise Sign-in Failures High", "warning", "auth", 20, "1m"),
}
# Labels a query may group or filter by: all bounded (as for the dashboard).
BOUNDED_LABELS = {
    "service_name",
    "deployment_environment_name",
    "http_response_status_code",
    "error_type",
    "le",
}
CONTACT_POINT = "spendwise-oncall-webhook"


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((ALERTING / name).read_text())


@pytest.fixture(scope="module")
def group() -> dict[str, Any]:
    (group,) = load("rules.yaml")["groups"]
    return group


@pytest.fixture(scope="module")
def rules(group) -> dict[str, dict]:
    return {rule["uid"]: rule for rule in group["rules"]}


def query(rule: dict) -> str:
    (data,) = [d for d in rule["data"] if d["refId"] == "A"]
    return data["model"]["expr"]


def condition(rule: dict) -> dict:
    (data,) = [d for d in rule["data"] if d["refId"] == rule["condition"]]
    return data["model"]


def test_every_alerting_file_parses_as_grafana_provisioning() -> None:
    names = sorted(path.name for path in ALERTING.iterdir())
    assert names == ["contact-points.yaml", "policies.yaml", "rules.yaml"]
    for name in names:
        assert load(name)["apiVersion"] == 1, name


def test_the_rule_pack(group, rules) -> None:
    assert (group["orgId"], group["name"], group["folder"]) == (1, "spendwise-api", "SpendWise")
    assert group["interval"] == "10s"  # evaluated every 10 seconds
    assert set(rules) == set(EXPECTED)
    for uid, (title, severity, category, threshold, pending) in EXPECTED.items():
        rule = rules[uid]
        assert rule["title"] == title
        assert len(uid) <= 40 and re.fullmatch(r"[a-z0-9-]+", uid)  # Grafana's UID rules
        assert rule["labels"] == {
            "service": "spendwise-api",
            "team": "spendwise",
            "severity": severity,
            "category": category,
        }
        model = condition(rule)
        assert model["type"] == "threshold" and model["expression"] == "A"
        assert model["conditions"] == [{"evaluator": {"type": "gt", "params": [threshold]}}]
        assert rule["for"] == pending
        assert rule.get("isPaused", False) is False


def test_quiet_means_ok_and_a_failing_query_means_an_alert(rules) -> None:
    for uid, rule in rules.items():
        # No traffic, no ratio: not an outage. A query that fails: Grafana's DatasourceError.
        assert (rule["noDataState"], rule["execErrState"]) == ("OK", "Error"), uid


def test_pending_periods_hold_over_several_evaluations(group, rules) -> None:
    seconds = {"10s": 10, "30s": 30, "1m": 60}
    for uid, rule in rules.items():
        # At least three evaluations above the threshold before anyone is notified.
        assert seconds[rule["for"]] >= 3 * seconds[group["interval"]], uid


def test_queries_read_the_dashboards_real_series_over_five_minutes(rules) -> None:
    dashboard = DASHBOARD.read_text()
    for uid, rule in rules.items():
        data = rule["data"][0]
        assert data["datasourceUid"] == "prometheus"  # LGTM's Prometheus (as the dashboard)
        assert data["model"]["datasource"] == {"type": "prometheus", "uid": "prometheus"}
        assert data["model"]["instant"] is True and data["model"]["range"] is False
        assert condition(rule)["datasource"] == {"type": "__expr__", "uid": "__expr__"}
        expr = query(rule)
        for metric in re.findall(r"(\w+)\{", expr):
            assert metric in dashboard, (uid, metric)  # no metric invented for alerting
        assert set(re.findall(r"\[(\w+)\]", expr)) == {"5m"}, uid
        for selector in re.findall(r"\{([^{}]*)\}", expr):
            assert selector.startswith('service_name="spendwise-api"'), (uid, selector)


def test_one_alert_per_environment_and_bounded_labels_only(rules) -> None:
    for uid, rule in rules.items():
        expr = query(rule)
        groupings = re.findall(r"by \(([^)]*)\)", expr)
        assert groupings, uid
        for grouping in groupings:
            labels = {label.strip() for label in grouping.split(",")}
            assert "deployment_environment_name" in labels and labels <= BOUNDED_LABELS, uid
        for label in re.findall(r"(\w+)=~?\"", expr):
            assert label in BOUNDED_LABELS, (uid, label)
        assert "on (deployment_environment_name)" in expr or "and on" not in expr


def test_ratios_never_divide_by_zero(rules) -> None:
    for uid, rule in rules.items():
        expr = " ".join(query(rule).split())
        if " / " in expr:
            denominator = expr.split(" / ", 1)[1]
            assert re.search(r"> 0 ?\)$", denominator), (uid, denominator)
    latency = " ".join(query(rules["spendwise-http-p95-latency"]).split())
    assert latency.startswith("histogram_quantile(0.95, sum by (deployment_environment_name, le)")
    assert latency.endswith("> 0)")  # only where there was traffic: never NaN


def test_user_mistakes_never_page(rules) -> None:
    expr = query(rules["spendwise-transaction-save-failures"])
    numerator = expr.split(" / ", 1)[0]
    assert 'error_type=~"database|internal"' in numerator
    assert "validation" not in expr


def test_annotations_explain_and_link_without_user_data(rules) -> None:
    panels = {panel["id"]: panel["title"] for panel in json.loads(DASHBOARD.read_text())["panels"]}
    for uid, rule in rules.items():
        annotations = rule["annotations"]
        assert set(annotations) == {
            "summary",
            "description",
            "runbook",
            "__dashboardUid__",
            "__panelId__",
        }, uid
        assert annotations["__dashboardUid__"] == "spendwise-overview"
        assert int(annotations["__panelId__"]) in panels, uid
        for key in ("summary", "description"):
            text = annotations[key]
            # A value, or none because the query failed: both read right.
            assert text.startswith("{{ if .Values.A }}") and text.endswith("{{ end }}"), uid
            assert "{{ else }}" in text
        # Templates read the environment label and the rule's own value, nothing else.
        for text in annotations.values():
            for action in re.findall(r"\{\{(.*?)\}\}", text):
                fields = set(re.findall(r"\.[A-Z]\w*(?:\.[A-Z]\w*)*", action))
                assert fields <= {".Values.A", ".Values.A.Value", ".Labels"}, (uid, action)
                if ".Labels" in action:
                    assert action.strip() == 'index .Labels "deployment_environment_name"'
        assert "threshold" in annotations["description"], uid


def keys(data: object) -> list[str]:
    """Every mapping key in a parsed YAML document, at any depth."""
    if isinstance(data, dict):
        return [str(k) for k in data] + [k for v in data.values() for k in keys(v)]
    if isinstance(data, list):
        return [k for v in data for k in keys(v)]
    return []


def test_the_files_hold_no_secret_dollar_or_production_url() -> None:
    for path in sorted(ALERTING.iterdir()):
        text = path.read_text()
        values = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        # Grafana expands $NAME in provisioning files: templates use .Labels / .Values instead.
        assert "$" not in values, path.name
        for key in keys(load(path.name)):
            for secret in ("password", "token", "secret", "authorization", "credential", "key"):
                assert secret not in key.lower(), (path.name, key)
        for url in re.findall(r"https?://[^\s\"']+", values):
            assert urlsplit(url).hostname == "alert-receiver", (path.name, url)
        for production in ("nip.io", "onrender.com", "amazonaws", "54.79.77.189"):
            assert production not in text, (path.name, production)


def test_the_contact_point_is_the_local_receiver() -> None:
    (contact_point,) = load("contact-points.yaml")["contactPoints"]
    assert contact_point["name"] == CONTACT_POINT
    (receiver,) = contact_point["receivers"]
    assert (receiver["uid"], receiver["type"]) == (CONTACT_POINT, "webhook")
    assert receiver["disableResolveMessage"] is False  # resolved notifications too
    settings = receiver["settings"]
    assert set(settings) == {"url", "httpMethod", "maxAlerts"}  # no credentials, no templates
    url = urlsplit(settings["url"])
    # The receiver's Docker DNS name on the internal network: not localhost, not the internet.
    assert (url.scheme, url.hostname, url.port, url.path) == (
        "http",
        "alert-receiver",
        8080,
        "/alerts",
    )
    assert settings["httpMethod"] == "POST"
    assert 1 <= settings["maxAlerts"] <= 20


def test_the_policy_routes_spendwise_alerts_to_the_webhook_without_spam() -> None:
    (policy,) = load("policies.yaml")["policies"]
    assert policy["receiver"] == CONTACT_POINT  # nothing falls through to a missing receiver
    (route,) = policy["routes"]
    assert route["receiver"] == CONTACT_POINT
    assert route["object_matchers"] == [["service", "=", "spendwise-api"]]
    assert route["group_by"] == ["alertname", "deployment_environment_name"]
    assert (route["group_wait"], route["group_interval"], route["repeat_interval"]) == (
        "30s",
        "1m",
        "4h",
    )
    assert "continue" not in route


# --- The receiver's container and Grafana's mount ----------------------------------------------


@pytest.fixture(scope="module")
def overlay() -> dict[str, Any]:
    return yaml.safe_load(OVERLAY.read_text())


def test_grafana_provisions_the_alerting_files_read_only(overlay) -> None:
    lgtm = overlay["services"]["lgtm"]
    assert (
        "./deploy/observability/grafana/alerting:/otel-lgtm/grafana/conf/provisioning/alerting:ro"
        in lgtm["volumes"]
    )
    assert lgtm["environment"]["GF_SERVER_ROOT_URL"] == "http://127.0.0.1:${GRAFANA_PORT:-3000}/"
    assert lgtm["networks"] == ["dashboard", "alerting"]


def test_the_receiver_is_internal_unprivileged_and_read_only(overlay) -> None:
    receiver = overlay["services"]["alert-receiver"]
    assert re.fullmatch(r"python:3\.13\.\d+-alpine3\.\d+@sha256:[0-9a-f]{64}", receiver["image"])
    assert receiver["command"] == ["python", "-I", "-u", "/receiver/alert_receiver.py"]
    for forbidden in ("ports", "expose", "privileged", "network_mode", "cap_add", "pid", "devices"):
        assert forbidden not in receiver, forbidden
    assert receiver["networks"] == ["alerting"]
    assert overlay["networks"]["alerting"] == {"internal": True}
    assert receiver["user"] == "65534:65534"
    assert receiver["read_only"] is True
    assert receiver["cap_drop"] == ["ALL"]
    assert receiver["security_opt"] == ["no-new-privileges:true"]
    assert (receiver["mem_limit"], receiver["pids_limit"]) == ("64m", 32)
    # Its own script, read-only, and nothing else: no Docker socket, no credentials.
    assert receiver["volumes"] == [
        "./deploy/observability/alert-receiver/alert_receiver.py:/receiver/alert_receiver.py:ro"
    ]
    assert "environment" not in receiver and "env_file" not in receiver
    (tmpfs,) = receiver["tmpfs"]
    assert tmpfs.startswith("/var/lib/alert-receiver:size=1m,")
    assert receiver["healthcheck"]["test"][:2] == ["CMD", "python"]


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
def test_alerting_is_never_part_of_a_deployment(path) -> None:
    text = (ROOT / path).read_text()
    for name in ("alert-receiver", CONTACT_POINT, "alerting"):
        assert name not in text, (path, name)
