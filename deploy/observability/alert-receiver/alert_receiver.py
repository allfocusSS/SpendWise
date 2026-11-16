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
- it never logs a payload.

With compose.oncall.yaml it also hands each normalized incident to the AI on-call responder
(deploy/observability/oncall-responder/): one HMAC-signed POST per incident, to the one URL in
ONCALL_RESPONDER_URL, signed with ONCALL_HMAC_SECRET (both from the environment). That is the
only call it makes; without both variables it makes none.

    python alert_receiver.py     # 0.0.0.0:8080, which in Compose is the internal network only
"""

import contextlib
import hashlib
import hmac
import http.client
import json
import math
import os
import queue
import re
import secrets
import signal
import socket
import socketserver
import sys
import threading
import time
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
READ_TIMEOUT = 5  # seconds a client may stay silent between two reads
REQUEST_DEADLINE = 10  # seconds for a whole request, headers and body, however it trickles in
MAX_CONNECTIONS = 16  # open at once, a thread each; the next is answered 503 at once
REAP_INTERVAL = 0.5  # how often the reaper looks for connections past their deadline
LENGTH = re.compile(r"[0-9]{1,9}")  # ASCII digits: "²", "١٢" and " 5" are not lengths
MAX_NUMBER = 10**15  # a measured value larger than this is not a measurement
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

# The handoff to the on-call responder.
HANDOFF_PATH = "/incidents"
HANDOFF_ATTEMPTS = 3
HANDOFF_TIMEOUT = 5  # seconds per attempt
HANDOFF_BACKOFF = 1.0  # seconds before the second attempt, doubled before the third
HANDOFF_QUEUE = 100
MIN_SECRET = 32  # characters


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
    if isinstance(value, float) and not math.isfinite(value):
        return None
    # Compared before it is converted: float() of a huge integer raises OverflowError.
    return round(float(value), 6) if abs(value) <= MAX_NUMBER else None


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
        self.lock = threading.Lock()  # requests are handled on several threads; saves must not mix
        self.save()

    def add(self, incidents: list[dict]) -> None:
        with self.lock:
            self.incidents.extend(incidents)
            self.save()

    def save(self) -> None:
        lines = "".join(
            json.dumps(i, sort_keys=True, ensure_ascii=True) + "\n" for i in self.incidents
        )
        partial = self.path.with_suffix(".partial")
        partial.write_text(lines)
        partial.replace(self.path)


def sign(secret: str, method: str, path: str, body: bytes) -> dict[str, str]:
    """Authentication headers for the responder: HMAC-SHA256 over method, path, time, nonce, body.

    The same scheme as oncall_responder/signing.py, which verifies it (a unit test keeps the two
    in step). The responder refuses a stale timestamp and a nonce it has seen.
    """
    stamp, nonce = str(int(time.time())), secrets.token_hex(16)
    signed = "\n".join(["v1", method, path, stamp, nonce, hashlib.sha256(body).hexdigest()])
    digest = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return {
        "X-SpendWise-Timestamp": stamp,
        "X-SpendWise-Nonce": nonce,
        "X-SpendWise-Signature": f"v1={digest}",
    }


class Forwarder:
    """Hands incidents to the responder from a background thread; Grafana never waits for it.

    Up to HANDOFF_ATTEMPTS tries per incident, each signed afresh. A refusal other than "try again
    later" (a 4xx) is final. What is logged is the outcome and never the incident.
    """

    def __init__(self, url: str, secret: str, sleep=time.sleep) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "http"
            or not parts.hostname
            or not parts.port
            or parts.path != HANDOFF_PATH
            or parts.username
            or parts.query
        ):
            raise ValueError(f"ONCALL_RESPONDER_URL must look like http://host:port{HANDOFF_PATH}")
        if len(secret) < MIN_SECRET:
            raise ValueError(f"ONCALL_HMAC_SECRET must be at least {MIN_SECRET} characters")
        self.host, self.port, self.secret, self.sleep = parts.hostname, parts.port, secret, sleep
        self.pending: queue.Queue[dict] = queue.Queue(maxsize=HANDOFF_QUEUE)

    def start(self) -> None:
        threading.Thread(target=self.work, daemon=True, name="handoff").start()

    def submit(self, incident: dict) -> None:
        try:
            self.pending.put_nowait(incident)
        except queue.Full:
            log("handoff: dropped an incident (queue full)")

    def work(self) -> None:
        while True:
            incident = self.pending.get()
            try:
                self.deliver(incident)
            except Exception as error:  # one bad incident must not end the handoff for the rest
                log(f"handoff: failed unexpectedly ({type(error).__name__})")
            finally:
                self.pending.task_done()

    def deliver(self, incident: dict) -> bool:
        body = json.dumps(incident, sort_keys=True, ensure_ascii=True).encode()
        for attempt in range(1, HANDOFF_ATTEMPTS + 1):
            status = self.post(body)
            if status is not None and 200 <= status < 300:
                log(f"handoff: delivered to the responder (HTTP {status}, attempt {attempt})")
                return True
            if status is not None and status < 500:
                log(f"handoff: refused by the responder (HTTP {status})")
                return False
            if attempt < HANDOFF_ATTEMPTS:
                self.sleep(HANDOFF_BACKOFF * 2 ** (attempt - 1))
        log(f"handoff: failed after {HANDOFF_ATTEMPTS} attempts")
        return False

    def post(self, body: bytes) -> int | None:
        headers = {"Content-Type": "application/json"}
        headers |= sign(self.secret, "POST", HANDOFF_PATH, body)
        connection = http.client.HTTPConnection(self.host, self.port, timeout=HANDOFF_TIMEOUT)
        try:
            connection.request("POST", HANDOFF_PATH, body=body, headers=headers)
            response = connection.getresponse()
            response.read(1024)
            return response.status
        except (OSError, http.client.HTTPException):
            return None
        finally:
            connection.close()


class Server(socketserver.ThreadingMixIn, HTTPServer):
    """One thread per connection, at most MAX_CONNECTIONS, each with an overall deadline.

    READ_TIMEOUT alone can't stop a slow client: it restarts on every byte, so a trickle holds
    the connection (and, on one thread, the whole receiver) indefinitely. A reaper thread cuts
    off any connection still open REQUEST_DEADLINE seconds after it was accepted.
    """

    daemon_threads = True
    request_queue_size = 32  # a burst of connections waits in the kernel, not reset by it

    def __init__(
        self, address: tuple[str, int], inbox: Inbox, forwarder: Forwarder | None = None
    ) -> None:
        super().__init__(address, Handler)
        self.inbox = inbox
        self.forwarder = forwarder
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.deadlines: dict[socket.socket, float] = {}  # open connection → monotonic deadline
        self.lock = threading.Lock()  # guards `deadlines`, and the reaper's use of its sockets
        self.closing = threading.Event()
        self.last_turned_away = 0.0
        threading.Thread(target=self.reap, daemon=True, name="receiver-reaper").start()

    def process_request(self, request: socket.socket, client_address) -> None:
        if not self.slots.acquire(blocking=False):
            return self.turn_away(request)
        with self.lock:
            self.deadlines[request] = time.monotonic() + REQUEST_DEADLINE
        try:
            threading.Thread(
                target=self.process_request_thread, args=(request, client_address), daemon=True
            ).start()
        except BaseException:  # no thread to be had: free the slot and let handle_error log it
            with self.lock:
                self.deadlines.pop(request, None)
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            with self.lock:  # off the reaper's list before the socket is closed, never after
                self.deadlines.pop(request, None)
            self.shutdown_request(request)
            self.slots.release()

    def turn_away(self, request: socket.socket) -> None:
        now = time.monotonic()
        if now - self.last_turned_away > 1:  # one line a second, not one per connection
            self.last_turned_away = now
            log("request: turned away (too many open connections)")  # before the answer
        body = b'{"error": "busy"}'
        head = b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n"
        with contextlib.suppress(OSError):
            request.settimeout(1)
            request.sendall(head + b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.shutdown_request(request)

    def reap(self) -> None:
        while not self.closing.wait(REAP_INTERVAL):
            now = time.monotonic()
            with self.lock:
                late = [c for c, deadline in self.deadlines.items() if deadline <= now]
                for connection in late:
                    del self.deadlines[connection]
                    log("request: dropped (open longer than the deadline)")  # then cut
                    with contextlib.suppress(OSError):  # wakes the thread blocked reading it
                        connection.shutdown(socket.SHUT_RDWR)

    def handle_error(self, request, client_address) -> None:
        # The class only: socketserver's default prints a traceback with the client's address.
        log(f"request failed ({type(sys.exc_info()[1]).__name__})")

    def server_close(self) -> None:
        self.closing.set()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "spendwise-alert-receiver"
    sys_version = ""
    timeout = READ_TIMEOUT  # a client that stops sending is dropped, not waited for

    def handle(self) -> None:
        # A client that goes away, or one the reaper cut off at the deadline, is not an error.
        with contextlib.suppress(OSError):
            super().handle()

    def do_POST(self) -> None:
        try:
            self.accept_alerts()
        except OSError:
            raise  # the connection is gone: handle() lets it go quietly
        except Exception as error:  # a bug costs this one request, with an answer, not a reset
            log(f"request failed ({type(error).__name__})")
            self.reply(500, error="internal error")

    def accept_alerts(self) -> None:
        if self.path != PATH:
            return self.reply(404, error="not found")
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, error="application/json only")
        raw_length = self.headers.get("Content-Length")
        if "Transfer-Encoding" in self.headers or raw_length is None:
            return self.reply(411, error="a Content-Length is required")
        if len(self.headers.get_all("Content-Length")) > 1 or not LENGTH.fullmatch(raw_length):
            return self.reply(400, error="invalid Content-Length")
        length = int(raw_length)
        if length > MAX_BODY:
            return self.reply(413, error=f"at most {MAX_BODY} bytes")
        body = self.rfile.read(length)
        if len(body) != length:
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
            if self.server.forwarder:
                self.server.forwarder.submit(i)
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


_LOG = threading.Lock()


def log(message: str) -> None:
    """One line, written whole: handler threads log concurrently and lines must not be mixed."""
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}\n"
    with _LOG:
        sys.stdout.write(line)
        sys.stdout.flush()


def forwarder_from_env() -> Forwarder | None:
    """The handoff, if configured: both variables or neither."""
    url, secret = (
        os.environ.get("ONCALL_RESPONDER_URL", ""),
        os.environ.get("ONCALL_HMAC_SECRET", ""),
    )
    if not url and not secret:
        return None
    if not (url and secret):
        raise ValueError("set both ONCALL_RESPONDER_URL and ONCALL_HMAC_SECRET, or neither")
    return Forwarder(url, secret)


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        forwarder = forwarder_from_env()
    except ValueError as error:  # the message names the variable, never its value
        print(f"configuration error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    server = Server(("0.0.0.0", PORT), Inbox(INCIDENTS_FILE), forwarder)
    if forwarder:
        forwarder.start()
    log(
        f"listening on :{PORT}{PATH}"
        + (" (handoff to the on-call responder on)" if forwarder else "")
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
