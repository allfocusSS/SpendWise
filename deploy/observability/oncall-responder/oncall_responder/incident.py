"""The incident the responder accepts: the alert receiver's `spendwise.incident.v1`, validated.

The receiver already normalized Grafana's webhook; this checks it again, because the responder
trusts nothing it is sent: the exact set of fields, each one's type, allowed values and length.
Text is made plain and scrubbed, links must lead to the configured Grafana, and anything outside
the contract is rejected rather than passed on to the model.
"""

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from oncall_responder.privacy import safe_text

SCHEMA = "spendwise.incident.v1"
FIELDS = frozenset(
    {
        "schema",
        "status",
        "alert",
        "kind",
        "rule_uid",
        "fingerprint",
        "severity",
        "category",
        "service",
        "team",
        "environment",
        "summary",
        "description",
        "runbook",
        "value",
        "starts_at",
        "ends_at",
        "grafana_url",
        "dashboard_url",
        "panel_url",
        "received_at",
    }
)
STATUSES = ("firing", "resolved")
KINDS = ("condition", "datasource_error", "no_data")
SEVERITIES = ("critical", "warning")
CATEGORIES = ("http", "transaction", "ai", "auth")
SERVICE = "spendwise-api"
MAX_VALUE = 10**15  # a measured value larger than this is not a measurement

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
FINGERPRINT = re.compile(r"[0-9a-f]{16}")
RULE_UID = re.compile(r"[A-Za-z0-9_-]{1,40}")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class InvalidIncident(ValueError):
    """Not a spendwise.incident.v1 this responder accepts."""


@dataclass(frozen=True)
class Incident:
    status: str
    alert: str
    kind: str
    rule_uid: str | None
    fingerprint: str
    severity: str
    category: str
    team: str | None
    environment: str | None
    summary: str | None
    description: str | None
    runbook: str | None
    value: float | None
    starts_at: str
    ends_at: str | None
    grafana_url: str | None
    dashboard_url: str | None
    panel_url: str | None
    received_at: str

    @property
    def report_id(self) -> str:
        """The same incident (alert, state and start) always gets the same report."""
        key = "|".join([self.fingerprint, self.status, self.starts_at, self.ends_at or ""])
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def for_prompt(self) -> dict:
        """What the model may see of the incident: bounded, validated fields only."""
        return {
            "status": self.status,
            "alert": self.alert,
            "kind": self.kind,
            "severity": self.severity,
            "category": self.category,
            "environment": self.environment,
            "summary": self.summary,
            "description": self.description,
            "runbook": self.runbook,
            "measured_value": self.value,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "dashboard_url": self.dashboard_url,
            "panel_url": self.panel_url,
        }


def parse_incident(
    data: object, grafana_origin: str | None = None, secrets: tuple[str, ...] = ()
) -> Incident:
    """The validated incident, or InvalidIncident naming the first thing wrong (never a value)."""
    if not isinstance(data, dict):
        raise InvalidIncident("not a JSON object")
    if set(data) != FIELDS:
        # The contract's own names may be listed; a sender's may not be echoed back or logged
        # (they could be any length, and anything at all), so they are counted.
        missing, extra = sorted(FIELDS - set(data)), len(set(data) - FIELDS)
        raise InvalidIncident(f"fields differ from the contract (missing {missing}, {extra} extra)")
    if data["schema"] != SCHEMA:
        raise InvalidIncident("schema is not spendwise.incident.v1")
    status = choice(data, "status", STATUSES)
    kind = choice(data, "kind", KINDS)
    if data["service"] != SERVICE:
        raise InvalidIncident("service is not spendwise-api")
    alert = safe_text(data["alert"], 120, secrets)
    if alert is None:
        raise InvalidIncident("alert is missing")
    starts_at = timestamp(data, "starts_at", required=True)
    ends_at = timestamp(data, "ends_at")
    if status == "firing" and ends_at is not None:
        raise InvalidIncident("a firing incident has no end")
    value = data["value"]
    if value is not None and not measurable(value):
        raise InvalidIncident("value is not a finite number")
    return Incident(
        status=status,
        alert=alert,
        kind=kind,
        rule_uid=matching(data, "rule_uid", RULE_UID),
        fingerprint=matching(data, "fingerprint", FINGERPRINT, required=True),
        severity=choice(data, "severity", SEVERITIES),
        category=choice(data, "category", CATEGORIES),
        team=matching(data, "team", NAME),
        environment=matching(data, "environment", NAME),
        summary=safe_text(data["summary"], 200, secrets),
        description=safe_text(data["description"], 1000, secrets),
        runbook=safe_text(data["runbook"], 1000, secrets),
        value=None if value is None else round(float(value), 6),
        starts_at=starts_at,
        ends_at=ends_at,
        grafana_url=link(data["grafana_url"], grafana_origin),
        dashboard_url=link(data["dashboard_url"], grafana_origin),
        panel_url=link(data["panel_url"], grafana_origin),
        received_at=timestamp(data, "received_at", required=True),
    )


def measurable(value: object) -> bool:
    """A real, finite number of a size a measurement could have."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    # Compared before any float() call: float(10**400) raises OverflowError.
    return abs(value) <= MAX_VALUE


def choice(data: dict, field: str, allowed: tuple[str, ...]) -> str:
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        raise InvalidIncident(f"{field} is not one of {list(allowed)}")
    return value


def matching(data: dict, field: str, pattern: re.Pattern, required: bool = False) -> str | None:
    value = data[field]
    if value is None and not required:
        return None
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InvalidIncident(f"{field} is malformed")
    return value


def timestamp(data: dict, field: str, required: bool = False) -> str | None:
    value = data[field]
    if value is None and not required:
        return None
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise InvalidIncident(f"{field} is not a UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise InvalidIncident(f"{field} is not a real date") from None
    return value


def origin(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        return None
    return f"{parts.scheme}://{parts.hostname}" + (f":{port}" if port else "")


def link(value: object, grafana_origin: str | None) -> str | None:
    """A link into the configured Grafana; anything else is dropped, not rejected."""
    if grafana_origin is None or not isinstance(value, str) or len(value) > 1024:
        return None
    if not value.isprintable() or " " in value:
        return None
    return value if origin(value) == grafana_origin else None
