"""SpendWise's alert receiver: where Grafana's `spendwise-oncall-webhook` contact point posts.

Local, demo and CI only (compose.dashboard.yaml; docs/observability.md, "Alerts"). Grafana posts
each alert notification here as JSON. The receiver checks it, turns every alert in it into a
normalized incident (see `incident()`), and keeps the latest incidents in INCIDENTS_FILE, one
JSON object per line. The AI on-call responder (the next milestone) is to read those incidents,
never Grafana's raw JSON.

Deliberately small and inert:
- the standard library only, one process, one request at a time;
- POST /alerts only, application/json only, at most MAX_BODY bytes, read within READ_TIMEOUT;
- the JSON is parsed as data: nothing in it is evaluated, rendered, fetched or executed;
- only allowlisted, bounded fields survive normalization: no labels map, no raw payload;
- it calls nothing, needs no credentials, and never logs a payload.

    python alert_receiver.py     # 0.0.0.0:8080, which in Compose is the internal network only
"""

import json
import math
import os
import re
import signal
import sys
import unicodedata
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = "spendwise.incident.v1"
PATH = "/alerts"
PORT = 8080
MAX_BODY = 256 * 1024  # Grafana sends at most 20 alerts per notification (maxAlerts)
MAX_ALERTS = 100
READ_TIMEOUT = 5  # seconds a client has to send its request
KEEP = 200  # incidents kept, newest last
INCIDENTS_FILE = Path(
    os.environ.get("ALERT_RECEIVER_INCIDENTS", "/var/lib/alert-receiver/incidents.jsonl")
)

STATUSES = {"firing", "resolved"}
SEVERITIES = {"critical", "warning"}
CATEGORIES = {"http", "transaction", "ai", "auth"}
# Grafana's own alerts for a rule whose query failed, or returned nothing when that alerts.
KINDS = {"DatasourceError": "datasource_error", "DatasourceNoData": "no_data"}
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
FINGERPRINT = re.compile(r"[0-9a-f]{16}")
RULE_UID = re.compile(r"[A-Za-z0-9_-]{1,40}")
TAG = re.compile(r"<[^>]*>")


class Rejected(ValueError):
    """Not a Grafana alert notification this receiver accepts."""


def normalize(payload: object, received_at: str) -> list[dict]:
    """Grafana's webhook notification (version 1) → one incident per alert in it."""
    if not isinstance(payload, dict):
        raise Rejected("not a JSON object")
    if payload.get("version") != "1":
        raise Rejected("not a Grafana webhook notification (version 1)")
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise Rejected("no alerts")
    if len(alerts) > MAX_ALERTS:
        raise Rejected("too many alerts")
    grafana = origin(payload.get("externalURL"))
    return [incident(alert, received_at, grafana) for alert in alerts]


def incident(alert: object, received_at: str, grafana: str | None = None) -> dict:
    """The normalized incident: fixed fields, each bounded, missing or invalid ones null.

    `grafana` is the sender's origin: links elsewhere are dropped.
    """
    if not isinstance(alert, dict):
        raise Rejected("an alert is not an object")
    labels, annotations = alert.get("labels"), alert.get("annotations", {})
    if not isinstance(labels, dict) or not isinstance(annotations, dict):
        raise Rejected("an alert without labels")
    status = alert.get("status")
    if status not in STATUSES:
        raise Rejected("an alert with an unknown status")
    alertname = text(labels.get("alertname"), 120)
    if not alertname:
        raise Rejected("an alert without a name")
    values = alert.get("values")
    return {
        "schema": SCHEMA,
        "status": status,
        # The rule's title; for Grafana's DatasourceError alerts, the rule that failed.
        "alert": text(labels.get("rulename"), 120) or alertname,
        "kind": KINDS.get(alertname, "condition"),
        "rule_uid": matching(RULE_UID, alert.get("ruleUID")),
        "fingerprint": matching(FINGERPRINT, alert.get("fingerprint")),
        "severity": labels.get("severity") if labels.get("severity") in SEVERITIES else None,
        "category": labels.get("category") if labels.get("category") in CATEGORIES else None,
        "service": matching(NAME, labels.get("service")),
        "team": matching(NAME, labels.get("team")),
        "environment": matching(NAME, labels.get("deployment_environment_name")),
        "summary": text(annotations.get("summary"), 200),
        "description": text(annotations.get("description"), 1000),
        "runbook": text(annotations.get("runbook"), 1000),
        # The rule's measured value (query A): an aggregate, never a user's data.
        "value": number(values.get("A")) if isinstance(values, dict) else None,
        "starts_at": timestamp(alert.get("startsAt")),
        "ends_at": timestamp(alert.get("endsAt")) if status == "resolved" else None,
        "grafana_url": link(alert.get("generatorURL"), grafana),
        "dashboard_url": link(alert.get("dashboardURL"), grafana),
        "panel_url": link(alert.get("panelURL"), grafana),
        "received_at": received_at,
    }


def text(value: object, limit: int) -> str | None:
    """Plain, single-line text: no markup, no control or format characters, at most `limit`."""
    if not isinstance(value, str):
        return None
    value = TAG.sub(" ", value[: limit * 4])
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value or None


def matching(pattern: re.Pattern, value: object) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return round(float(value), 6) if math.isfinite(value) else None


def timestamp(value: object) -> str | None:
    """RFC 3339 → UTC to the second; Go's zero time (an alert that hasn't ended) → None."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    # Python reads at most microseconds; Grafana writes up to nanoseconds.
    value = re.sub(r"(\.\d{6})\d+", r"\1", value)
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None or moment.year < 2000:
        return None
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def origin(value: object) -> str | None:
    """scheme://host[:port] of an http(s) URL without credentials, else None."""
    if not isinstance(value, str) or len(value) > 1024:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return f"{parts.scheme}://{parts.hostname}" + (f":{port}" if port else "")


def link(value: object, grafana: str | None) -> str | None:
    """A link into the Grafana that sent the notification (same origin as its externalURL)."""
    if grafana is None or not isinstance(value, str) or not value.isprintable() or " " in value:
        return None
    return value if origin(value) == grafana else None


class Inbox:
    """The latest incidents, newest last, rewritten whole (one JSON object per line)."""

    def __init__(self, path: Path, keep: int = KEEP) -> None:
        self.path = path
        self.incidents: deque[dict] = deque(maxlen=keep)
        self.save()

    def add(self, incidents: list[dict]) -> None:
        self.incidents.extend(incidents)
        self.save()

    def save(self) -> None:
        lines = "".join(
            json.dumps(i, sort_keys=True, ensure_ascii=True) + "\n" for i in self.incidents
        )
        partial = self.path.with_suffix(".partial")
        partial.write_text(lines)
        partial.replace(self.path)


class Server(HTTPServer):
    def __init__(self, address: tuple[str, int], inbox: Inbox) -> None:
        super().__init__(address, Handler)
        self.inbox = inbox


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "spendwise-alert-receiver"
    sys_version = ""
    timeout = READ_TIMEOUT  # a client that stops sending is dropped, not waited for

    def do_POST(self) -> None:
        if self.path != PATH:
            return self.reply(404, error="not found")
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, error="application/json only")
        length = self.headers.get("Content-Length", "")
        if "Transfer-Encoding" in self.headers or not length.isdigit():
            return self.reply(411, error="a Content-Length is required")
        if int(length) > MAX_BODY:
            return self.reply(413, error=f"at most {MAX_BODY} bytes")
        body = self.rfile.read(int(length))
        if len(body) != int(length):
            return self.reply(400, error="incomplete body")
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            return self.reply(400, error="malformed JSON")
        received_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        try:
            incidents = normalize(payload, received_at)
        except Rejected as reason:
            return self.reply(422, error=str(reason))
        self.server.inbox.add(incidents)
        for i in incidents:
            log(f"incident: {i['status']} {i['alert']!r} ({i['environment'] or 'no environment'})")
        self.reply(202, accepted=len(incidents))

    def refuse(self) -> None:
        self.reply(405, error="POST only")

    do_GET = do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = refuse

    def reply(self, status: int, **fields: object) -> None:
        body = json.dumps(fields).encode()
        self.send_response(status)
        if status == 405:
            self.send_header("Allow", "POST")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # The method, path and status only: never another path as sent, a header or the body.
    def log_request(self, code: object = "-", size: object = "-") -> None:
        path = PATH if getattr(self, "path", None) == PATH else "(other path)"
        log(f"{self.command or '-'} {path} {int(code) if isinstance(code, int) else '-'}")

    def log_error(self, format: str, *args: object) -> None:
        log("refused a malformed or incomplete request")


def log(message: str) -> None:
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}", flush=True)


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server = Server(("0.0.0.0", PORT), Inbox(INCIDENTS_FILE))
    log(f"listening on :{PORT}{PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
