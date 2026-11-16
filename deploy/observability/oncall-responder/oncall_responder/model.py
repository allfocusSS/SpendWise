"""The model the responder asks. Only a deterministic fake exists; a real one is a seam.

A model is anything with `complete(system, user) -> str` that returns the JSON text the system
prompt describes. The responder treats that text like any other untrusted input: analysis.py
validates it against a strict schema and a content policy before any of it reaches a report.

The SpendWise app's AIProvider (backend/app/ai) interprets transactions and has no free-form
method, so it is not reused here, and its Anthropic provider doesn't exist yet. When a real
provider is added it takes this shape, behind ONCALL_MODEL, with its key read from the
environment (never from Git), and the same validation applies to what it returns.

FakeModel is rule-based and offline. It reads the prompt's structured numbers (never log lines,
alert text or labels it could echo) and writes a report from fixed playbooks, so the same
evidence always gives the same answer, and nothing a log or an alert says can change it.
"""

import json
import re
from typing import Protocol

from oncall_responder.prompt import EVIDENCE_BLOCK, INCIDENT_BLOCK

# Alert thresholds, as provisioned in deploy/observability/grafana/alerting/rules.yaml.
THRESHOLDS = {"ai": 0.10, "http_error": 0.05, "http_p95": 1.0, "transaction": 0.01, "auth": 20.0}


class ModelUnavailable(Exception):
    """The configured model can't be built."""


class Model(Protocol):
    provider: str
    name: str
    version: str

    def complete(self, system: str, user: str) -> str: ...


MODELS = ("fake",)  # what ONCALL_MODEL may name


def build_model(name: str) -> Model:
    if name == "fake":
        return FakeModel()
    raise ModelUnavailable(
        f"ONCALL_MODEL={name!r} is not available: only 'fake' exists. A real provider needs its "
        "own implementation, a key from the environment, and egress this network doesn't have."
    )


def block(user: str, name: str) -> object:
    found = re.search(rf"<<<{name}>>>\n(.*?)\n<<<END_{name}>>>", user, re.S)
    if not found:
        raise ValueError(f"no {name} block")
    return json.loads(found.group(1))


def percent(ratio: float) -> str:
    return f"{ratio * 100:.1f}%"


class FakeModel:
    provider = "fake"
    name = "spendwise-fake-oncall"
    version = "1"

    def complete(self, system: str, user: str) -> str:
        incident, evidence = block(user, INCIDENT_BLOCK), block(user, EVIDENCE_BLOCK)
        return json.dumps(self.analyze(incident, {item["query_id"]: item for item in evidence}))

    # --- Evidence access: numbers only -------------------------------------------------------

    @staticmethod
    def rows(evidence: dict, query: str) -> list[dict]:
        item = evidence.get(query)
        data = item["data"] if item and item.get("available", True) else []
        return data if isinstance(data, list) else []

    def value(self, evidence: dict, query: str) -> float | None:
        rows = self.rows(evidence, query)
        return rows[0]["value"] if rows else None

    def total(self, evidence: dict, query: str, **labels: str) -> float:
        return sum(
            row["value"]
            for row in self.rows(evidence, query)
            if all(row["labels"].get(k) == v for k, v in labels.items())
        )

    # --- Playbooks ---------------------------------------------------------------------------

    def analyze(self, incident: dict, evidence: dict) -> dict:
        category, environment = (
            incident["category"],
            incident["environment"] or "an unknown environment",
        )
        if incident["kind"] != "condition":
            return self.monitoring_blind(environment, incident["kind"])
        playbooks = {
            "ai": self.analyze_ai,
            "http": self.analyze_http,
            "transaction": self.analyze_transaction,
            "auth": self.analyze_auth,
        }
        found = playbooks[category](evidence)
        if incident["status"] == "resolved":
            found = self.resolved(found, environment)
        else:
            found["assessment"] = found["assessment"].replace("@ENV@", environment)
        found["escalation_required"] = (
            incident["severity"] == "critical" and incident["status"] == "firing"
        )
        return found

    def monitoring_blind(self, environment: str, kind: str) -> dict:
        what = "failed" if kind == "datasource_error" else "returned no data"
        return {
            "assessment": (
                f"Grafana's query for this alert rule {what}, so the alert's state in "
                f"{environment} is unknown. That says nothing about the application itself."
            ),
            "likely_causes": [
                {
                    "cause": (
                        "The metrics backend may be down, restarting or unreachable from Grafana."
                    ),
                    "certainty": "possible",
                    "evidence_ids": ["incident"],
                }
            ],
            "recommended_actions": [
                {
                    "action": "Check that Prometheus is up and reachable from Grafana.",
                    "kind": "investigate",
                },
                {
                    "action": "Open the SpendWise dashboard and see whether its panels load.",
                    "kind": "verify",
                },
            ],
            "verification_steps": [
                "The rule's query should succeed again and the alert return to Normal."
            ],
            "confidence": "low",
            "escalation_required": True,
            "limitations": [
                "No metrics were available, so the application's state was not assessed."
            ],
        }

    def resolved(self, found: dict, environment: str) -> dict:
        return {
            "assessment": (
                f"The alert has resolved in {environment}: the measured value is back inside its "
                "threshold. The current evidence is attached; this report does not say what fixed "
                "it."
            ),
            "likely_causes": [],
            "recommended_actions": [
                {
                    "action": (
                        "Watch the same dashboard panel for a while to see that it stays resolved."
                    ),
                    "kind": "monitor",
                },
            ],
            "verification_steps": found["verification_steps"],
            "confidence": found["confidence"],
            "escalation_required": False,
            "limitations": found["limitations"],
        }

    def analyze_ai(self, evidence: dict) -> dict:
        ratio = self.value(evidence, "ai.failure_ratio")
        requests = self.total(evidence, "ai.requests")
        failures = self.total(evidence, "ai.errors_by_type")
        provider = self.total(evidence, "ai.errors_by_type", error_type="provider")
        validation = self.total(evidence, "ai.errors_by_type", error_type="validation")
        causes = []
        if failures > 0 and provider / failures >= 0.8:
            causes.append(
                {
                    "cause": (
                        "The AI provider may be failing or unavailable: provider-type errors make "
                        f"up {percent(provider / failures)} of the recent AI parse failures."
                    ),
                    "certainty": "probable" if failures >= 3 else "possible",
                    "evidence_ids": ["prometheus:ai.errors_by_type", "prometheus:ai.failure_ratio"],
                }
            )
        elif failures > 0 and validation / failures > 0.5:
            causes.append(
                {
                    "cause": (
                        "The provider may be answering, but its answers are being rejected as "
                        "unusable: validation-type errors dominate."
                    ),
                    "certainty": "possible",
                    "evidence_ids": ["prometheus:ai.errors_by_type"],
                }
            )
        measured = ratio is not None
        assessment = (
            f"{percent(ratio)} of AI transaction parses failed over the last 5 minutes in @ENV@ "
            f"(alert threshold {percent(THRESHOLDS['ai'])}). Causes below are inferences."
            if measured
            else "The AI parse failure ratio could not be measured from the collected evidence."
        )
        return {
            "assessment": assessment,
            "likely_causes": causes,
            "recommended_actions": [
                {
                    "action": (
                        "Open the dashboard's AI transaction parsing row and compare failures by "
                        "error type with the evidence."
                    ),
                    "kind": "investigate",
                },
                {
                    "action": (
                        "Check the AI provider's own status page and any recent change to its "
                        "credentials or quota."
                    ),
                    "kind": "investigate",
                },
                {
                    "action": (
                        "Watch the failure ratio; it should fall under the threshold once the "
                        "provider recovers."
                    ),
                    "kind": "monitor",
                },
                {
                    "action": (
                        "If the provider stays down, a human can decide whether to switch AI entry "
                        "off until it recovers; manual entry keeps working."
                    ),
                    "kind": "human_change",
                },
            ],
            "verification_steps": [
                "The dashboard's parse success rate returns above 90%.",
                "New AI parse requests rise while parse failures stay flat.",
            ],
            "confidence": "medium" if measured and requests >= 3 else "low",
            "escalation_required": False,
            "limitations": [
                "The provider's own status was not checked; any cause is inferred from error "
                "types.",
                "Counts come from Prometheus increase() over 5 minutes, which extrapolates and "
                "can be fractional.",
            ],
        }

    def analyze_http(self, evidence: dict) -> dict:
        ratio = self.value(evidence, "http.error_ratio")
        p95 = self.value(evidence, "http.p95_latency")
        routes = self.rows(evidence, "http.errors_by_route")
        versions = len(self.rows(evidence, "common.version"))
        causes, parts = [], []
        if ratio is not None and ratio >= THRESHOLDS["http_error"]:
            parts.append(
                f"{percent(ratio)} of requests were server errors (threshold "
                f"{percent(THRESHOLDS['http_error'])})"
            )
            if routes and routes[0]["labels"].get("http_route"):
                causes.append(
                    {
                        "cause": (
                            f"The server errors may be concentrated on the route "
                            f"{routes[0]['labels']['http_route']}."
                        ),
                        "certainty": "possible",
                        "evidence_ids": ["prometheus:http.errors_by_route"],
                    }
                )
        if p95 is not None and p95 >= THRESHOLDS["http_p95"]:
            parts.append(
                f"the p95 request time was {p95:.2f} s (threshold {THRESHOLDS['http_p95']:.0f} s)"
            )
        if versions >= 2:
            causes.append(
                {
                    "cause": (
                        "More than one service version is reporting, so a version change may be "
                        "under way."
                    ),
                    "certainty": "possible",
                    "evidence_ids": ["prometheus:common.version"],
                }
            )
        assessment = (
            "Over the last 5 minutes in @ENV@, "
            + " and ".join(parts)
            + ". Causes below are inferences."
            if parts
            else "No HTTP threshold is exceeded in the collected evidence for @ENV@ right now."
        )
        return {
            "assessment": assessment,
            "likely_causes": causes,
            "recommended_actions": [
                {
                    "action": (
                        "Open the dashboard's Service health row and the traces and logs linked "
                        "from it."
                    ),
                    "kind": "investigate",
                },
                {
                    "action": (
                        "Look at the slowest or failing traces for the route in the evidence."
                    ),
                    "kind": "investigate",
                },
                {
                    "action": (
                        "Check whether the service restarted or changed version around the start "
                        "time."
                    ),
                    "kind": "verify",
                },
            ],
            "verification_steps": [
                "The 5xx share and the p95 latency panels return inside their thresholds.",
            ],
            "confidence": "medium" if parts else "low",
            "escalation_required": False,
            "limitations": [
                "The route and version hints are correlations, not proof of a cause.",
                "Rates come from Prometheus over 5 minutes; logs and traces cover 15.",
            ],
        }

    def analyze_transaction(self, evidence: dict) -> dict:
        ratio = self.value(evidence, "transaction.system_failure_ratio")
        database = self.total(evidence, "transaction.failed_by_type", error_type="database")
        internal = self.total(evidence, "transaction.failed_by_type", error_type="internal")
        causes = []
        if database + internal > 0:
            layer = "in the database layer" if database >= internal else "inside the application"
            dominant = "database" if database >= internal else "internal"
            causes.append(
                {
                    "cause": (
                        f"Saves may be failing {layer}: {dominant}-type errors dominate the "
                        "system failures."
                    ),
                    "certainty": "possible",
                    "evidence_ids": ["prometheus:transaction.failed_by_type"],
                }
            )
        assessment = (
            f"{percent(ratio)} of transaction save attempts failed for a system reason over the "
            f"last 5 minutes in @ENV@ (threshold {percent(THRESHOLDS['transaction'])}). Causes "
            f"below are inferences."
            if ratio is not None
            else "The system failure ratio for transaction saves could not be measured."
        )
        return {
            "assessment": assessment,
            "likely_causes": causes,
            "recommended_actions": [
                {
                    "action": (
                        "Open the dashboard's Failed saves per minute panel, split by error type."
                    ),
                    "kind": "investigate",
                },
                {
                    "action": "Look for error logs and failing traces around the start time.",
                    "kind": "investigate",
                },
                {"action": "Check the database's health and connection limits.", "kind": "verify"},
            ],
            "verification_steps": [
                "New transaction saves succeed and the failure ratio returns under the threshold."
            ],
            "confidence": "medium" if ratio is not None else "low",
            "escalation_required": False,
            "limitations": [
                "Rejected input (validation errors) is not counted as a failure here.",
                "The error type says which layer reported the failure, not why.",
            ],
        }

    def analyze_auth(self, evidence: dict) -> dict:
        refused = self.value(evidence, "auth.refused_per_minute")
        logins = (self.value(evidence, "auth.login_request_rate") or 0) * 60
        causes = []
        if refused is not None and logins > 0 and refused / logins >= 0.8:
            causes.append(
                {
                    "cause": (
                        "Most sign-in attempts are being refused; that fits password guessing or a "
                        "client that cannot sign in, and the evidence cannot tell which."
                    ),
                    "certainty": "possible",
                    "evidence_ids": [
                        "prometheus:auth.refused_per_minute",
                        "prometheus:auth.login_request_rate",
                    ],
                }
            )
        assessment = (
            f"About {refused:.1f} sign-ins per minute were refused over the last 5 minutes in "
            f"@ENV@ "
            f"(threshold {THRESHOLDS['auth']:.0f}). Causes below are inferences."
            if refused is not None
            else "The refused sign-in rate could not be measured."
        )
        return {
            "assessment": assessment,
            "likely_causes": causes,
            "recommended_actions": [
                {
                    "action": (
                        "Compare the refused sign-ins panel with the login request rate on the "
                        "dashboard."
                    ),
                    "kind": "investigate",
                },
                {
                    "action": (
                        "If it looks like guessing, a human can decide on stricter limits for "
                        "sign-in attempts."
                    ),
                    "kind": "human_change",
                },
            ],
            "verification_steps": ["The refused sign-in rate returns under the threshold."],
            "confidence": "medium" if refused is not None else "low",
            "escalation_required": False,
            "limitations": [
                "The metric never says which accounts were targeted, by design.",
            ],
        }
