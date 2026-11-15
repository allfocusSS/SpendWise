"""End to end: a SpendWise metric changes, an alert fires, and the on-call webhook hears of it.

The real image, PostgreSQL, grafana/otel-lgtm and the alert receiver run in Compose
(compose.dashboard.yaml). Grafana evaluates the alert rules provisioned from Git
(deploy/observability/grafana/alerting/). Nothing is mocked along the chain:

    SpendWise metric → Prometheus → Grafana rule evaluation → Pending → Alerting
    → notification policy → webhook contact point → alert receiver → normalized incident

Each stage is a fixture, run once and in this order, so a test asks for the stage it checks:
1. `quiet`: real traffic with canary personal data, a user's validation mistakes and a few
   refused sign-ins. Every rule's PromQL runs on Prometheus and stays under its threshold,
   every rule is Normal, and the receiver has heard nothing.
2. `firing`: AI parse failures over 10% through the real provider path (no HTTP route calls AI
   parsing yet: integration/ai_traffic.py). The metric moves first, then the rule goes
   Pending and Alerting, and Grafana's firing notification reaches the receiver.
3. `resolved`: healthy AI parses bring the failure rate back under 10%: Normal, and the
   resolved notification.
4. `datasource_down`, last: Prometheus is stopped inside LGTM. The rules' queries fail, and
   Grafana's DatasourceError alert reaches the receiver: a broken data source never looks
   healthy.

Canaries (an email, a password, a description, a category name, an amount, AI input text, an
exception message, the session cookie and the database password) must not appear in any rule,
alert, notification record or incident.
"""

import json
import math
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import yaml

from integration import ai_traffic
from integration.lgtm import Backends, wait_for
from integration.stack import Stack

ALERTING = Path(__file__).resolve().parents[2] / "deploy/observability/grafana/alerting"
(GROUP,) = yaml.safe_load((ALERTING / "rules.yaml").read_text())["groups"]
RULES = {rule["uid"]: rule for rule in GROUP["rules"]}
AI_RULE = "spendwise-ai-parse-failures"
CONTACT_POINT = "spendwise-oncall-webhook"
INCIDENTS = "/var/lib/alert-receiver/incidents.jsonl"
# The normalized incident's fields, as documented (deploy/observability/alert-receiver/examples/).
EXAMPLE_INCIDENT = ALERTING.parents[1] / "alert-receiver/examples/incident-firing.json"
ENVIRONMENT = "local"  # the stack's APP_ENV, as the metrics carry it
SELECT = 'service_name="spendwise-api"'

CANARY = secrets.token_hex(4)
CANARY_EMAIL = f"canary-{CANARY}@example.com"
CANARY_PASSWORD = f"Canary-Password-{CANARY}"
CANARY_DESCRIPTION = f"Canary rent to Askar {CANARY}"
CANARY_CATEGORY = f"Canary Category {CANARY}"
CANARY_AI_TEXT = f"CanaryMerchant{CANARY} taxi 2500 yesterday"
CANARY_EXCEPTION = f"Canary provider exploded on {CANARY}"  # the outage's exception message
CANARY_AMOUNT = 987_654_321_07

SAVED, USER_MISTAKES, REFUSED_SIGN_INS = 2, 2, 3
# Over the AI rule's 10%: 3 of 6 parses fail. Then 60 healthy ones: 3 of 66, back under it.
FIRE_PARSES, FIRE_OUTAGES, RECOVERY_PARSES = 3, 3, 60

# Stops Prometheus inside the LGTM container (LGTM doesn't restart a component that exits).
STOP_PROMETHEUS = r"""
for proc in /proc/[0-9]*; do
  case "$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null)" in
    ./prometheus/prometheus*) kill "${proc#/proc/}" && echo "stopped prometheus" ;;
  esac
done
"""


def expr(uid: str) -> str:
    (query,) = [d for d in RULES[uid]["data"] if d["refId"] == "A"]
    return query["model"]["expr"]


def threshold(uid: str) -> float:
    (condition,) = [d for d in RULES[uid]["data"] if d["refId"] == RULES[uid]["condition"]]
    ((value,),) = [c["evaluator"]["params"] for c in condition["model"]["conditions"]]
    return value


class Alerting:
    """Grafana's alerting state (read-only APIs only) and the receiver's incidents."""

    def __init__(self, grafana: httpx.Client, stack: Stack) -> None:
        self.grafana = grafana
        self.stack = stack

    def get(self, path: str, **params) -> object:
        response = self.grafana.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def rules(self) -> dict[str, dict]:
        """Rule state and health, by UID (Grafana's Prometheus-style rules API)."""
        groups = self.get("/api/prometheus/grafana/api/v1/rules")["data"]["groups"]
        return {rule["uid"]: rule for group in groups for rule in group["rules"]}

    def history(self, uid: str) -> list[tuple[str, str, dict]]:
        """Grafana's own record of the rule's state changes in ENVIRONMENT, oldest first."""
        frame = self.get("/api/v1/rules/history", ruleUID=uid)["data"]["values"]
        return [
            (prev, new, json.loads(data))
            for _, text, prev, new, data in sorted(zip(*frame, strict=True))
            if f"deployment_environment_name={ENVIRONMENT}" in text
        ]

    def notified(self) -> list[dict]:
        """What Grafana's Alertmanager holds: the alerts it routes to contact points."""
        return self.get("/api/alertmanager/grafana/api/v2/alerts")

    def incidents(self) -> list[dict]:
        out = self.stack.compose("exec", "-T", "alert-receiver", "cat", INCIDENTS).stdout
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def incidents_once(self, status: str) -> list[dict] | None:
        """All incidents, as soon as one with this status has arrived."""
        incidents = self.incidents()
        return incidents if any(i["status"] == status for i in incidents) else None


@pytest.fixture(scope="module")
def backends(grafana: httpx.Client) -> Backends:
    backends = Backends(grafana)  # Grafana and its data sources are ready (conftest.py)
    # The app's zero series (metrics.initialize) arrived: from here on every event is an increase.
    wait_for(
        "the app's first metrics in Prometheus",
        lambda: backends.query(f"spendwise_transaction_created_total{{{SELECT}}}"),
    )
    return backends


@pytest.fixture(scope="module")
def alerting(grafana: httpx.Client, stack: Stack, backends: Backends) -> Alerting:
    alerting = Alerting(grafana, stack)

    def evaluated() -> bool:
        rules = alerting.rules()
        return set(rules) >= set(RULES) and all(
            rules[uid]["health"] == "ok" and not rules[uid]["lastEvaluation"].startswith("0001")
            for uid in RULES
        )

    wait_for("every rule's first evaluation", evaluated)
    return alerting


def evaluated_since(alerting: Alerting, moment: str) -> bool:
    """Every SpendWise rule was evaluated after `moment` (Grafana's RFC 3339 timestamps)."""
    rules = alerting.rules()
    return all(rules[uid]["lastEvaluation"] > moment for uid in RULES)


def grafana_now(alerting: Alerting) -> str:
    return max(rule["lastEvaluation"] for rule in alerting.rules().values())


# --- 1. Quiet traffic --------------------------------------------------------------------------


@dataclass
class Quiet:
    states_before: dict[str, str]
    results_before: dict[str, list]
    session: str


@pytest.fixture(scope="module")
def quiet(stack: Stack, backends: Backends, alerting: Alerting) -> Quiet:
    states_before = {uid: rule["state"] for uid, rule in alerting.rules().items()}
    results_before = {uid: backends.query(expr(uid)) for uid in RULES}
    with httpx.Client(base_url=stack.base_url, timeout=30) as client:
        signup = client.post(
            "/api/auth/signup", json={"email": CANARY_EMAIL, "password": CANARY_PASSWORD}
        )
        assert signup.status_code == 201, signup.text
        session = client.cookies["spendwise_session"]
        category = client.post("/api/categories", json={"name": CANARY_CATEGORY, "type": "expense"})
        assert category.status_code == 201, category.text
        body = {
            "amount_cents": CANARY_AMOUNT,
            "type": "expense",
            "category_id": category.json()["id"],
            "description": CANARY_DESCRIPTION,
            "occurred_on": "2026-11-15",
        }
        for _ in range(SAVED):
            assert client.post("/api/transactions", json=body).status_code == 201
        # A user's mistakes: half the save attempts are refused input (a validation error).
        for _ in range(USER_MISTAKES):
            mistake = client.post("/api/transactions", json=body | {"category_id": 999_999_999})
            assert mistake.status_code == 422
        assert client.get("/api/analytics/summary").status_code == 200
        for _ in range(REFUSED_SIGN_INS):
            refused = client.post(
                "/api/auth/login", json={"email": CANARY_EMAIL, "password": "not-the-password"}
            )
            assert refused.status_code == 401

    def exported() -> bool:
        def total(metric: str, matchers: str = "") -> float:
            return backends.value(f"sum({metric}{{{SELECT}{matchers}}})") or 0

        return (
            total("spendwise_transaction_created_total") >= SAVED
            and total("spendwise_transaction_create_error_total", ', error_type="validation"')
            >= USER_MISTAKES
            and total("spendwise_auth_sign_in_failure_total") >= REFUSED_SIGN_INS
        )

    wait_for("the quiet traffic in Prometheus", exported)
    # Grafana has evaluated every rule against that data, twice over.
    for _ in range(2):
        moment = grafana_now(alerting)
        wait_for("the next rule evaluation", lambda m=moment: evaluated_since(alerting, m))
    return Quiet(states_before, results_before, session)


def test_rules_contact_point_and_policy_are_provisioned_from_git(alerting: Alerting) -> None:
    ruler = alerting.get("/api/ruler/grafana/api/v1/rules", subtype="cortex")
    (group,) = ruler[GROUP["folder"]]
    assert (group["name"], group["interval"]) == (GROUP["name"], GROUP["interval"])
    served = {rule["grafana_alert"]["uid"]: rule for rule in group["rules"]}
    assert set(served) == set(RULES)
    for uid, rule in RULES.items():
        grafana_alert = served[uid]["grafana_alert"]
        assert grafana_alert["title"] == rule["title"]
        assert grafana_alert["provenance"] == "file"  # read-only in the UI and API
        assert grafana_alert["no_data_state"] == "OK"
        assert grafana_alert["exec_err_state"] == "Error"
        assert served[uid]["for"] == rule["for"]
        assert served[uid]["labels"] == rule["labels"]
        assert served[uid]["annotations"] == rule["annotations"]
        assert [d["model"].get("expr") for d in grafana_alert["data"]] == [
            d["model"].get("expr") for d in rule["data"]
        ]

    (contact_point,) = alerting.get("/api/v1/provisioning/contact-points")
    assert contact_point["name"] == CONTACT_POINT
    assert contact_point["type"] == "webhook"
    assert contact_point["settings"]["url"] == "http://alert-receiver:8080/alerts"
    assert contact_point["provenance"] == "file"

    policy = alerting.get("/api/v1/provisioning/policies")
    assert policy["provenance"] == "file"
    assert policy["receiver"] == CONTACT_POINT
    (route,) = policy["routes"]
    assert route["receiver"] == CONTACT_POINT
    assert route["object_matchers"] == [["service", "=", "spendwise-api"]]
    assert route["group_by"] == ["alertname", "deployment_environment_name"]


def test_quiet_traffic_keeps_every_rule_normal(quiet: Quiet, alerting: Alerting) -> None:
    assert set(quiet.states_before.values()) == {"inactive"}  # Normal before any traffic
    for uid, rule in alerting.rules().items():
        assert (rule["state"], rule["health"]) == ("inactive", "ok"), (uid, rule)
        assert all(a["state"].startswith("Normal") for a in rule["alerts"]), (uid, rule["alerts"])
    assert not [a for a in alerting.notified() if a["labels"].get("service") == "spendwise-api"]
    assert alerting.incidents() == []


def test_every_alert_query_runs_on_real_prometheus(quiet: Quiet, backends: Backends) -> None:
    for uid in RULES:
        for result in (quiet.results_before[uid], backends.query(expr(uid))):
            for series in result:
                # One series per environment, labelled with nothing else.
                assert series["metric"] == {"deployment_environment_name": ENVIRONMENT}, uid
                value = float(series["value"][1])
                assert math.isfinite(value) and value <= threshold(uid), (uid, value)

    value = {uid: backends.value(expr(uid)) for uid in RULES}
    # Traffic without server errors: a real 0, not "no data".
    assert value["spendwise-http-5xx-rate"] == 0
    assert 0 < value["spendwise-http-p95-latency"] < threshold("spendwise-http-p95-latency")
    # Half the save attempts were the user's mistakes; none failed for a system reason.
    mistakes = f'spendwise_transaction_create_error_total{{{SELECT}, error_type="validation"}}'
    assert backends.value(f"sum(increase({mistakes}[5m]))") > 0
    assert value["spendwise-transaction-save-failures"] == 0
    # No AI requests yet: no data (Normal), never a division by zero.
    assert value[AI_RULE] is None
    assert 0 < value["spendwise-sign-in-failures"] < threshold("spendwise-sign-in-failures")


def test_the_receiver_takes_only_grafana_notifications(stack: Stack) -> None:
    def post(*curl: str, path: str = "/alerts", shell_input: str = "") -> int:
        command = " ".join(
            [
                *([shell_input, "|"] if shell_input else []),
                "curl -s -o /dev/null -w '%{http_code}'",
                *curl,
                f"http://alert-receiver:8080{path}",
            ]
        )
        # From Grafana's container: the only one on the receiver's network.
        return int(stack.compose("exec", "-T", "lgtm", "sh", "-c", command).stdout)

    json_type = "-H 'Content-Type: application/json'"
    junk = json.dumps(
        {"version": "1", "alerts": [{"status": "x", "labels": {"alertname": CANARY}}]}
    )
    assert post("-X GET") == 405
    assert post("-X POST -H 'Content-Type: text/plain' --data x") == 415
    assert post(f"-X POST {json_type} --data '{{not json'") == 400
    assert post(f"-X POST {json_type} --data '{{\"alerts\": []}}'") == 422
    assert post(f"-X POST {json_type} --data '{junk}'") == 422
    assert post(f"-X POST {json_type} --data '{{}}'", path="/other") == 404
    # Too big: refused on the headers (the body, asked for with Expect, is never read).
    big = "head -c 300000 /dev/zero | tr '\\0' a"
    expect = "-H 'Expect: 100-continue'"
    assert post(f"-X POST {json_type} {expect} --data-binary @-", shell_input=big) == 413
    chunked = f"-X POST {json_type} -H 'Transfer-Encoding: chunked' --data '{{}}'"
    assert post(chunked) == 411
    receiver_log = stack.compose("logs", "--no-log-prefix", "alert-receiver").stdout
    assert "listening on :8080/alerts" in receiver_log
    assert CANARY not in receiver_log  # rejected bodies are never logged


def test_the_receiver_is_internal_only_and_locked_down(stack: Stack) -> None:
    published = {
        name: [(p["URL"], p["TargetPort"]) for p in service["Publishers"] if p.get("PublishedPort")]
        for name, service in stack.services().items()
    }
    # The app (its local port) and Grafana, both on loopback; nothing else.
    assert {name: ports for name, ports in published.items() if ports} == {
        "app": [("127.0.0.1", 8000)],
        "lgtm": [("127.0.0.1", 3000)],
    }
    receiver = stack.inspect("alert-receiver")
    host = receiver["HostConfig"]
    assert host["ReadonlyRootfs"] is True and host["Privileged"] is False
    assert host["CapDrop"] == ["ALL"] and not host.get("CapAdd")
    assert host["SecurityOpt"] == ["no-new-privileges:true"]
    assert receiver["Config"]["User"] == "65534:65534"
    assert not any("docker.sock" in m["Source"] for m in receiver["Mounts"])
    (network,) = receiver["NetworkSettings"]["Networks"]
    assert network == f"{stack.project}_alerting"
    details = subprocess.run(
        ["docker", "network", "inspect", network], capture_output=True, text=True, check=True
    )
    assert json.loads(details.stdout)[0]["Internal"] is True  # no route out
    # The app isn't on that network: it can't even resolve the receiver's name.
    probe = (
        "import socket\n"
        "try:\n    socket.create_connection(('alert-receiver', 8080), 3)\n"
        "except OSError:\n    print('unreachable')"
    )
    assert "unreachable" in stack.compose("exec", "-T", "app", "python", "-c", probe).stdout


# --- 2. Firing ---------------------------------------------------------------------------------


@dataclass
class Firing:
    value: float  # the AI rule's PromQL in Prometheus, once the failures arrived
    states: list[str]  # the rule's states as polled, from before the traffic, each change once
    routed: dict  # the alert in Grafana's Alertmanager
    incidents: list[dict]  # the receiver's incidents once the notification arrived


@pytest.fixture(scope="module")
def firing(stack: Stack, backends: Backends, alerting: Alerting, quiet: Quiet) -> Firing:
    states = [alerting.rules()[AI_RULE]["state"]]
    ai_traffic.send(
        stack,
        text=CANARY_AI_TEXT,
        category=CANARY_CATEGORY,
        parses=FIRE_PARSES,
        outages=FIRE_OUTAGES,
        outage_message=CANARY_EXCEPTION,
    )

    def over_threshold() -> float | None:
        value = backends.value(expr(AI_RULE))
        return value if value is not None and value > threshold(AI_RULE) else None

    value = wait_for("the AI failure rate over its threshold in Prometheus", over_threshold)

    def fired() -> bool:
        state = alerting.rules()[AI_RULE]["state"]
        if state != states[-1]:
            states.append(state)
        return state == "firing"

    wait_for("the AI rule to fire", fired)
    routed = wait_for(
        "the alert in Grafana's Alertmanager",
        lambda: next(
            (a for a in alerting.notified() if a["labels"]["alertname"] == RULES[AI_RULE]["title"]),
            None,
        ),
    )
    incidents = wait_for(
        "the firing notification at the receiver", lambda: alerting.incidents_once("firing")
    )
    return Firing(value, states, routed, incidents)


def test_ai_parse_failures_fire_the_alert(firing: Firing, backends: Backends, alerting) -> None:
    # The metric changed first: the real counters, then the rule's own expression.
    errors = f'spendwise_ai_parse_error_total{{{SELECT}, error_type="provider"}}'
    requests = f"spendwise_ai_parse_request_total{{{SELECT}}}"
    assert backends.value(f"sum({errors})") >= FIRE_OUTAGES
    assert backends.value(f"sum({requests})") >= FIRE_PARSES + FIRE_OUTAGES
    assert firing.value > threshold(AI_RULE)
    # Then Grafana evaluated it: Normal, Pending for the rule's `for`, then Alerting.
    assert firing.states == ["inactive", "pending", "firing"]
    pending, fired, *_ = alerting.history(AI_RULE)
    assert (pending[0], pending[1]) == ("Normal", "Pending")
    assert (fired[0], fired[1]) == ("Pending", "Alerting")
    for _, _, data in (pending, fired):
        assert data["values"]["A"] > threshold(AI_RULE)
    # And routed it by the notification policy to the webhook contact point.
    assert firing.routed["receivers"] == [{"name": CONTACT_POINT}]
    assert firing.routed["labels"]["deployment_environment_name"] == ENVIRONMENT


def test_the_webhook_delivers_the_firing_notification(firing: Firing, stack: Stack) -> None:
    (incident,) = firing.incidents  # one notification for one alert: nothing else was sent
    assert {k: incident[k] for k in ("schema", "status", "kind", "rule_uid")} == {
        "schema": "spendwise.incident.v1",
        "status": "firing",
        "kind": "condition",
        "rule_uid": AI_RULE,
    }
    labels = RULES[AI_RULE]["labels"]
    assert incident["alert"] == RULES[AI_RULE]["title"]
    assert incident["severity"] == labels["severity"] == "warning"
    assert incident["category"] == labels["category"] == "ai"
    assert incident["service"] == "spendwise-api" and incident["team"] == "spendwise"
    assert incident["environment"] == ENVIRONMENT
    assert incident["summary"] == f"AI parse failures above 10% in {ENVIRONMENT}"
    assert re.fullmatch(
        r"[\d.]+% of AI transaction parsing requests in the local environment failed over the "
        r"last 5 minutes \(threshold 10%\)\. .+",
        incident["description"],
    ), incident["description"]
    assert incident["runbook"].startswith("Open the SpendWise dashboard's AI")
    assert incident["value"] > threshold(AI_RULE)
    assert incident["starts_at"] and incident["ends_at"] is None
    grafana = f"http://127.0.0.1:{stack.extra_env['GRAFANA_PORT']}"
    assert incident["grafana_url"] == f"{grafana}/alerting/grafana/{AI_RULE}/view?orgId=1"
    assert incident["dashboard_url"].startswith(f"{grafana}/d/spendwise-overview?")
    assert incident["panel_url"].endswith("&viewPanel=19")


# --- 3. Resolved -------------------------------------------------------------------------------


@dataclass
class Resolved:
    value: float
    incidents: list[dict]


@pytest.fixture(scope="module")
def resolved(stack: Stack, backends: Backends, alerting: Alerting, firing: Firing) -> Resolved:
    ai_traffic.send(
        stack,
        text=CANARY_AI_TEXT,
        category=CANARY_CATEGORY,
        parses=RECOVERY_PARSES,
        outages=0,
        outage_message=CANARY_EXCEPTION,
    )

    def under_threshold() -> list[float] | None:
        value = backends.value(expr(AI_RULE))
        return [value] if value is not None and value <= threshold(AI_RULE) else None

    (value,) = wait_for("the AI failure rate back under its threshold", under_threshold)
    wait_for("the AI rule to resolve", lambda: alerting.rules()[AI_RULE]["state"] == "inactive")
    incidents = wait_for(
        "the resolved notification at the receiver", lambda: alerting.incidents_once("resolved")
    )
    return Resolved(value, incidents)


def test_recovery_resolves_the_alert_with_one_resolved_notification(
    resolved: Resolved, firing: Firing, alerting: Alerting
) -> None:
    assert 0 < resolved.value <= threshold(AI_RULE)
    assert alerting.rules()[AI_RULE]["state"] == "inactive"
    *_, recovered = alerting.history(AI_RULE)
    assert (recovered[0], recovered[1]) == ("Alerting", "Normal")
    assert recovered[2]["values"]["A"] <= threshold(AI_RULE)

    # Exactly two notifications for the incident, from this rule alone: no spam, no noise.
    first, last = resolved.incidents
    assert first == firing.incidents[0]
    assert last["status"] == "resolved" and last["rule_uid"] == AI_RULE
    assert last["fingerprint"] == first["fingerprint"]  # the same alert
    assert last["starts_at"] == first["starts_at"] < last["ends_at"]
    assert last["value"] <= threshold(AI_RULE)


def test_no_canary_reaches_any_rule_alert_or_incident(
    resolved: Resolved, alerting: Alerting, stack: Stack, quiet: Quiet
) -> None:
    canaries = (
        CANARY,
        CANARY_EMAIL,
        CANARY_PASSWORD,
        CANARY_DESCRIPTION,
        CANARY_CATEGORY,
        CANARY_AI_TEXT,
        CANARY_EXCEPTION,
        str(CANARY_AMOUNT),
        quiet.session,
        stack.db_password,
    )
    seen = {
        "rule definitions": alerting.get("/api/ruler/grafana/api/v1/rules"),
        "rule states and alerts": alerting.get("/api/prometheus/grafana/api/v1/rules"),
        "Alertmanager alerts": alerting.notified(),
        "state history": [alerting.get("/api/v1/rules/history", ruleUID=uid) for uid in RULES],
        "incidents": resolved.incidents,
        "receiver log": stack.compose("logs", "--no-log-prefix", "alert-receiver").stdout,
    }
    for name, data in seen.items():
        text = data if isinstance(data, str) else json.dumps(data)
        for canary in canaries:
            assert canary not in text, (name, canary)
    # The incidents hold only the envelope's fields: no labels map, no raw payload.
    fields = set(json.loads(EXAMPLE_INCIDENT.read_text()))
    assert all(set(incident) == fields for incident in resolved.incidents)


# --- 4. Data source down (last: Prometheus stays stopped) ---------------------------------------


@pytest.fixture(scope="module")
def datasource_down(stack: Stack, alerting: Alerting, resolved: Resolved) -> list[dict]:
    stopped = stack.compose("exec", "-T", "lgtm", "bash", "-c", STOP_PROMETHEUS)
    assert "stopped prometheus" in stopped.stdout, stopped.stdout + stopped.stderr
    wait_for(
        "every rule's query to fail",
        lambda: all(alerting.rules()[uid]["health"] == "error" for uid in RULES),
    )
    return wait_for(
        "Grafana's DatasourceError notification at the receiver",
        lambda: [i for i in alerting.incidents() if i["kind"] == "datasource_error"],
        deadline=180,
    )


def test_a_failing_query_alerts_instead_of_looking_healthy(
    datasource_down: list[dict], alerting: Alerting
) -> None:
    for uid, rule in alerting.rules().items():
        assert rule["health"] == "error", uid  # never "ok" or "nodata"
    for incident in datasource_down:
        uid = incident["rule_uid"]
        assert uid in RULES
        assert incident["status"] == "firing"
        assert incident["alert"] == RULES[uid]["title"]
        assert incident["severity"] == RULES[uid]["labels"]["severity"]
        assert incident["category"] == RULES[uid]["labels"]["category"]
        assert incident["environment"] is None  # no query result, so no environment
        assert incident["value"] is None
        assert incident["summary"].endswith("unknown: its query failed")
        assert "Prometheus is up and reachable from Grafana" in incident["description"]
