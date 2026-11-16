"""`spendwise.oncall.report.v1`: the on-call report, and the check every stored report passes.

The shape keeps the three kinds of statement apart, each marked with its `basis`:
- `evidence[]` is **observed**: built by the responder from what the backends returned, never
  from the model's words;
- `likely_causes[]` is **inference**: the model's, each citing evidence ids it rests on;
- `recommended_actions[]` is **recommendation**: advice for a human, always
  `requires_human_approval: true`.
`actions_executed` is always empty: the responder has no way to execute anything.
"""

import json
import re
from datetime import UTC, datetime

from oncall_responder.analysis import (
    ACTION_KINDS,
    ASSESSMENT,
    CERTAINTY,
    CONFIDENCE,
    INCIDENT_ID,
    ITEM,
    MAX_ACTIONS,
    MAX_CAUSES,
    MAX_CITED,
    MAX_STEPS,
    POLICY,
    RANK,
    Analysis,
    AnalysisRejected,
    check_text,
    confidence_ceiling,
)
from oncall_responder.evidence import Evidence, has_data
from oncall_responder.incident import CATEGORIES, NAME, SEVERITIES, STATUSES, Incident
from oncall_responder.privacy import plain, scrub
from oncall_responder.signing import SCHEME

SCHEMA = "spendwise.oncall.report.v1"
MAX_REPORT = 24 * 1024
MAX_EVIDENCE = 14
MAX_LIMITATIONS = 10
MAX_DATA = 4000
WINDOW = {"metrics_seconds": 300, "logs_and_traces_seconds": 900}

FIELDS = frozenset(
    {
        "schema",
        "report_id",
        "incident",
        "severity",
        "category",
        "environment",
        "observed_at",
        "evidence_window",
        "assessment",
        "evidence",
        "likely_causes",
        "recommended_actions",
        "verification_steps",
        "confidence",
        "escalation_required",
        "limitations",
        "advisory_only",
        "actions_executed",
        "model",
        "handoff",
    }
)
INCIDENT_FIELDS = frozenset(
    {
        "fingerprint",
        "status",
        "kind",
        "alert",
        "rule_uid",
        "starts_at",
        "ends_at",
        "grafana_url",
        "dashboard_url",
        "panel_url",
        "received_at",
    }
)
EVIDENCE_FIELDS = frozenset({"id", "basis", "available", "source", "query_id", "summary", "data"})
EVIDENCE_ID = re.compile(r"(?:incident|(?:prometheus|loki|tempo):[a-z0-9_.]{1,60})")
REPORT_ID = re.compile(r"[0-9a-f]{16}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MODEL_FIELDS = frozenset({"provider", "name", "version", "answer"})
# Keys whose values are identifiers or validated links, not prose.
NOT_PROSE = frozenset(
    {"fingerprint", "report_id", "rule_uid", "grafana_url", "dashboard_url", "panel_url"}
)


TITLE = re.compile(r"[A-Za-z0-9 .,:()%/+&_-]{1,120}")
WITHHELD = "[alert title withheld]"


def report_title(alert: str) -> str:
    """The alert's name if it reads like a title; otherwise a marker.

    The title is the one free-text field copied from the incident. A rule's title is plain words;
    anything with markup, a URL, a command, a secret or instruction-like text is not stored.
    """
    hostile = any(
        POLICY[rule].search(alert)
        for rule in ("url", "shell", "command", "injection-echo", "secrets", "alerting-change")
    )
    return alert if TITLE.fullmatch(alert) and not hostile else WITHHELD


def now_iso(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def incident_evidence(incident: Incident) -> dict:
    """The incident as evidence: only validated fields, so no free text of its own."""
    where = incident.environment or "an unknown environment"
    measured = "not reported" if incident.value is None else str(incident.value)
    return {
        "id": INCIDENT_ID,
        "basis": "observed",
        "available": True,
        "source": "incident",
        "query_id": INCIDENT_ID,
        "summary": (
            f"Grafana reported this alert {incident.status} in {where} "
            f"(severity {incident.severity}, category {incident.category}); "
            f"measured value {measured}."
        ),
        "data": {
            "status": incident.status,
            "severity": incident.severity,
            "category": incident.category,
            "environment": incident.environment,
            "measured_value": incident.value,
            "starts_at": incident.starts_at,
        },
    }


def build_report(
    incident: Incident,
    evidence: Evidence,
    analysis: Analysis,
    model: object,
    answer: str,
    now: float,
) -> dict:
    limitations = [*analysis.limitations, *(plain(p, ITEM) for p in evidence.problems)]
    return {
        "schema": SCHEMA,
        "report_id": incident.report_id,
        "incident": {
            "fingerprint": incident.fingerprint,
            "status": incident.status,
            "kind": incident.kind,
            "alert": report_title(incident.alert),
            "rule_uid": incident.rule_uid,
            "starts_at": incident.starts_at,
            "ends_at": incident.ends_at,
            "grafana_url": incident.grafana_url,
            "dashboard_url": incident.dashboard_url,
            "panel_url": incident.panel_url,
            "received_at": incident.received_at,
        },
        "severity": incident.severity,
        "category": incident.category,
        "environment": incident.environment,
        "observed_at": now_iso(now),
        "evidence_window": WINDOW,
        "assessment": analysis.assessment,
        "evidence": [incident_evidence(incident), *(i.report() for i in evidence.items)],
        "likely_causes": [{"basis": "inference", **cause} for cause in analysis.causes],
        "recommended_actions": [
            {"basis": "recommendation", **action, "requires_human_approval": True}
            for action in analysis.actions
        ],
        "verification_steps": list(analysis.steps),
        "confidence": analysis.confidence,
        "escalation_required": analysis.escalation_required,
        "limitations": [text for text in limitations if text][:MAX_LIMITATIONS],
        "advisory_only": True,
        "actions_executed": [],
        "model": {
            "provider": getattr(model, "provider", "unknown"),
            "name": getattr(model, "name", "unknown"),
            "version": getattr(model, "version", "unknown"),
            "answer": answer,
        },
        "handoff": {"authenticated": True, "scheme": SCHEME},
    }


def validate_report(report: object, secrets: tuple[str, ...] = ()) -> list[str]:
    """Why a report isn't acceptable; empty if it is. Values never appear in the reasons."""
    problems: list[str] = []

    def need(ok: bool, what: str) -> bool:
        if not ok:
            problems.append(what)
        return ok

    def prose(value: object, limit: int, what: str) -> None:
        try:
            check_text(value, limit, what, secrets)
        except AnalysisRejected as rejected:
            problems.append(rejected.code)

    if not need(isinstance(report, dict) and set(report) == FIELDS, "fields"):
        return problems
    assert isinstance(report, dict)
    need(report["schema"] == SCHEMA, "schema")
    need(
        isinstance(report["report_id"], str) and bool(REPORT_ID.fullmatch(report["report_id"])),
        "report_id",
    )
    need(
        report["severity"] in SEVERITIES and report["category"] in CATEGORIES,
        "severity-or-category",
    )
    need(
        report["environment"] is None or bool(NAME.fullmatch(str(report["environment"]))),
        "environment",
    )
    need(bool(TIMESTAMP.fullmatch(str(report["observed_at"]))), "observed_at")
    need(report["evidence_window"] == WINDOW, "evidence_window")
    need(report["advisory_only"] is True, "advisory_only")
    need(report["actions_executed"] == [], "actions_executed")
    need(report["handoff"] == {"authenticated": True, "scheme": SCHEME}, "handoff")
    need(report["confidence"] in CONFIDENCE, "confidence")
    need(isinstance(report["escalation_required"], bool), "escalation_required")

    incident = report["incident"]
    if need(isinstance(incident, dict) and set(incident) == INCIDENT_FIELDS, "incident-fields"):
        need(incident["status"] in STATUSES, "incident-status")
        need(report_title(str(incident["alert"])) == incident["alert"], "incident-alert")
        need(scrub(str(incident["alert"]), secrets) == incident["alert"], "incident-alert-secret")

    model = report["model"]
    if need(isinstance(model, dict) and set(model) == MODEL_FIELDS, "model-fields"):
        need(all(isinstance(v, str) and len(v) <= 80 for v in model.values()), "model-values")

    prose(report["assessment"], ASSESSMENT, "assessment")
    observed: dict[str, str] = {}  # evidence that found something: id → its source
    evidence = report["evidence"]
    if need(isinstance(evidence, list) and 1 <= len(evidence) <= MAX_EVIDENCE, "evidence-count"):
        for entry in evidence:
            if not need(
                isinstance(entry, dict) and set(entry) == EVIDENCE_FIELDS, "evidence-fields"
            ):
                continue
            need(entry["basis"] == "observed", "evidence-basis")
            need(bool(EVIDENCE_ID.fullmatch(str(entry["id"]))), "evidence-id")
            need(
                isinstance(entry["summary"], str) and len(entry["summary"]) <= 600,
                "evidence-summary",
            )
            summary, data = str(entry["summary"]), json.dumps(entry["data"])
            # Evidence is built from allowlisted labels, where service_version is a commit SHA.
            need(scrub(summary, secrets, keep_sha=True) == summary, "evidence-summary-secret")
            need(len(data) <= MAX_DATA, "evidence-data-size")
            need(scrub(data, secrets, keep_sha=True) == data, "evidence-data-secret")
            if entry["available"] is True and has_data(entry["source"], entry["data"]):
                observed[str(entry["id"])] = str(entry["source"])
    for entry in report["likely_causes"] if isinstance(report["likely_causes"], list) else [None]:
        if need(
            isinstance(entry, dict)
            and set(entry) == {"basis", "cause", "certainty", "evidence_ids"},
            "cause-fields",
        ):
            need(entry["basis"] == "inference" and entry["certainty"] in CERTAINTY, "cause-basis")
            cited = entry["evidence_ids"]
            need(
                isinstance(cited, list)
                and 1 <= len(cited) <= MAX_CITED
                and all(isinstance(i, str) and i in observed for i in cited),
                "cause-evidence",
            )
            prose(entry["cause"], ITEM, "cause")
    need(
        isinstance(report["likely_causes"], list) and len(report["likely_causes"]) <= MAX_CAUSES,
        "cause-count",
    )
    sources = {source for source in observed.values() if source != "incident"}
    ceiling = RANK[confidence_ceiling(sources)]
    need(RANK.get(str(report["confidence"]), 3) <= ceiling, "confidence-above-evidence")
    actions = report["recommended_actions"]
    if need(isinstance(actions, list) and len(actions) <= MAX_ACTIONS, "action-count"):
        for entry in actions:
            if need(
                isinstance(entry, dict)
                and set(entry) == {"basis", "action", "kind", "requires_human_approval"},
                "action-fields",
            ):
                need(entry["basis"] == "recommendation", "action-basis")
                need(entry["kind"] in ACTION_KINDS, "action-kind")
                need(entry["requires_human_approval"] is True, "action-approval")
                prose(entry["action"], ITEM, "action")
    for key, limit in (("verification_steps", MAX_STEPS), ("limitations", MAX_LIMITATIONS)):
        entries = report[key]
        if need(isinstance(entries, list) and len(entries) <= limit, f"{key}-count"):
            for text in entries:
                prose(text, ITEM, key)
    need(len(json.dumps(report)) <= MAX_REPORT, "report-size")
    return problems
