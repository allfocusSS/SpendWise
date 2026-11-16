"""The alert receiver (deploy/observability/alert-receiver/alert_receiver.py).

Normalization is checked against Grafana's real webhook notifications, captured from the local
stack (examples/grafana-*.json; only the Grafana port was changed to 3000). The HTTP server runs
here on a free loopback port. The alert smoke test (alerts_smoke/) runs it in Compose, behind
Grafana.
"""

import ast
import copy
import http.client
import importlib.util
import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from oncall_responder.signing import Nonces, verify
from oncall_support import INJECTION, SECRET, Stalled, raw_request, status_of

ROOT = Path(__file__).resolve().parents[3]
RECEIVER_DIR = ROOT / "deploy" / "observability" / "alert-receiver"
EXAMPLES = RECEIVER_DIR / "examples"

_spec = importlib.util.spec_from_file_location("alert_receiver", RECEIVER_DIR / "alert_receiver.py")
ar = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ar
_spec.loader.exec_module(ar)

RECEIVED = "2026-11-15T16:21:01Z"
CANARY = "canary-7f3a9c@example.com"


def example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text())


@pytest.fixture
def firing() -> dict:
    return example("grafana-firing.json")


def one(payload: dict) -> dict:
    (incident,) = ar.normalize(payload, RECEIVED)
    return incident


# --- Grafana's payload, and the incident made of it -------------------------------------------


def test_the_real_firing_notification_becomes_the_documented_incident(firing) -> None:
    assert one(firing) == example("incident-firing.json")


def test_the_real_resolved_notification_ends_the_same_incident(firing) -> None:
    started, ended = one(firing), one(example("grafana-resolved.json"))
    assert ended["status"] == "resolved"
    assert ended["fingerprint"] == started["fingerprint"]
    assert ended["starts_at"] == started["starts_at"] < ended["ends_at"]
    assert ended["value"] < 0.1 < started["value"]


def test_grafanas_payload_has_what_the_receiver_reads(firing) -> None:
    # The input contract: Grafana's webhook format version 1, as received (not assumed).
    assert firing["version"] == "1"
    assert {"status", "alerts", "externalURL", "groupKey", "truncatedAlerts"} <= set(firing)
    (alert,) = firing["alerts"]
    assert {
        "status",
        "labels",
        "annotations",
        "startsAt",
        "endsAt",
        "fingerprint",
        "ruleUID",
        "values",
        "generatorURL",
        "dashboardURL",
        "panelURL",
    } <= set(alert)
    assert {"alertname", "severity", "category", "service", "team"} <= set(alert["labels"])
    assert set(alert["annotations"]) == {"summary", "description", "runbook"}


def test_a_failed_query_is_a_datasource_error_incident(firing) -> None:
    alert = firing["alerts"][0]
    title = alert["labels"]["alertname"]
    alert["labels"] = {
        k: v for k, v in alert["labels"].items() if k != "deployment_environment_name"
    } | {"alertname": "DatasourceError", "rulename": title, "datasource_uid": "prometheus"}
    error = 'Post "http://127.0.0.1:9090/api/v1/query": connection refused'
    alert["annotations"] |= {"Error": error, "summary": "AI parse failure rate unknown"}
    alert["values"] = {}
    incident = one(firing)
    assert (incident["kind"], incident["alert"]) == ("datasource_error", title)
    assert incident["environment"] is None and incident["value"] is None
    assert incident["rule_uid"] == "spendwise-ai-parse-failures"
    assert "9090" not in json.dumps(incident)  # Grafana's raw error annotation is not kept


def test_only_the_envelope_survives(firing) -> None:
    alert = firing["alerts"][0]
    alert["labels"] |= {"email": CANARY, "user_id": "42", "path": "/api/users/42"}
    alert["annotations"] |= {"token": CANARY, "Error": CANARY}
    alert |= {"extra": CANARY, "values": {"A": 0.3, "B": CANARY}}
    firing |= {"message": CANARY, "commonLabels": {"email": CANARY}}
    incident = one(firing)
    assert set(incident) == set(example("incident-firing.json"))
    assert CANARY not in json.dumps(incident)


# --- Field by field ----------------------------------------------------------------------------


def test_text_is_plain_single_line_and_bounded(firing) -> None:
    annotations = firing["alerts"][0]["annotations"]
    annotations["summary"] = "<script>alert(1)</script><b>Rate</b>\nhigh\x00\x1b[31m‮ok " * 20
    annotations["description"] = "x" * 5000
    incident = one(firing)
    summary = incident["summary"]
    assert "<" not in summary and ">" not in summary
    assert all(c.isprintable() for c in summary)
    assert "‮" not in summary and "\n" not in summary
    assert len(summary) <= 200 and summary.endswith("…")
    assert len(incident["description"]) == 1000


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "http://evil.example/alerting/grafana/x/view",  # another origin than Grafana's
        "http://127.0.0.1:4000/d/spendwise-overview",  # another port
        "http://user:secret@127.0.0.1:3000/d/spendwise-overview",
        "http://127.0.0.1:3000/d/x y",
        "http://[::1/broken",
        42,
    ],
)
def test_links_must_lead_to_the_grafana_that_sent_them(firing, link) -> None:
    firing["alerts"][0] |= {"generatorURL": link, "dashboardURL": link, "panelURL": link}
    incident = one(firing)
    assert incident["grafana_url"] is incident["dashboard_url"] is incident["panel_url"] is None


def test_without_a_valid_external_url_no_link_is_kept(firing) -> None:
    firing["externalURL"] = "ftp://127.0.0.1:3000/"
    assert one(firing)["grafana_url"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("severity", "page-everyone"),
        ("category", "billing"),
        ("service", "Spendwise API"),
        ("team", "x" * 64),
        ("deployment_environment_name", "prod; drop"),
    ],
)
def test_labels_outside_their_allowed_values_become_null(firing, field, value) -> None:
    firing["alerts"][0]["labels"][field] = value
    key = {"deployment_environment_name": "environment"}.get(field, field)
    assert one(firing)[key] is None


@pytest.mark.parametrize(
    ("field", "value", "key"),
    [
        ("fingerprint", "not-hex", "fingerprint"),
        ("ruleUID", "../../etc/passwd", "rule_uid"),
        ("values", {"A": float("nan")}, "value"),
        ("values", {"A": float("inf")}, "value"),
        ("values", {"A": "0.5"}, "value"),
        ("values", {"A": True}, "value"),
        ("values", None, "value"),
        ("startsAt", "yesterday", "starts_at"),
        ("startsAt", "2026-11-15T16:20:30", "starts_at"),  # no time zone
    ],
)
def test_invalid_values_become_null(firing, field, value, key) -> None:
    firing["alerts"][0][field] = value
    assert one(firing)[key] is None


def test_timestamps_are_utc_to_the_second(firing) -> None:
    firing["alerts"][0]["startsAt"] = "2026-11-15T21:20:30.123456789+05:00"
    assert one(firing)["starts_at"] == "2026-11-15T16:20:30Z"
    firing["alerts"][0] |= {"status": "resolved", "endsAt": "0001-01-01T00:00:00Z"}
    assert one(firing)["ends_at"] is None  # Go's zero time: not ended


def broken(change) -> dict:
    payload = example("grafana-firing.json")
    change(payload)
    return payload


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "firing",
        {},
        broken(lambda p: p.update(version="2")),
        broken(lambda p: p.update(alerts=[])),
        broken(lambda p: p.update(alerts={"0": {}})),
        broken(lambda p: p.update(alerts=p["alerts"] * (ar.MAX_ALERTS + 1))),
        broken(lambda p: p.update(alerts=["not an alert"])),
        broken(lambda p: p["alerts"][0].pop("labels")),
        broken(lambda p: p["alerts"][0].update(annotations=["x"])),
        broken(lambda p: p["alerts"][0].update(status="exploded")),
        broken(lambda p: p["alerts"][0]["labels"].pop("alertname")),
        broken(lambda p: p["alerts"][0]["labels"].update(alertname="<b></b>")),
    ],
)
def test_anything_but_a_grafana_notification_is_rejected(payload) -> None:
    with pytest.raises(ar.Rejected):
        ar.normalize(copy.deepcopy(payload), RECEIVED)


# --- The HTTP server ---------------------------------------------------------------------------


@pytest.fixture
def server(tmp_path, monkeypatch) -> Iterator[ar.Server]:
    monkeypatch.setattr(ar.Handler, "timeout", 1)
    server = ar.Server(("127.0.0.1", 0), ar.Inbox(tmp_path / "incidents.jsonl"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def request(
    server: ar.Server, method: str, path: str = "/alerts", body: bytes | None = None, **headers
) -> tuple[int, dict, dict]:
    connection = http.client.HTTPConnection(*server.server_address, timeout=5)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), json.loads(data) if data else {}


def raw(server: ar.Server, request_bytes: bytes) -> bytes:
    with socket.create_connection(server.server_address, timeout=5) as sock:
        sock.sendall(request_bytes)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


def stored(server: ar.Server) -> list[dict]:
    return [json.loads(line) for line in server.inbox.path.read_text().splitlines()]


JSON = {"Content-Type": "application/json"}


def test_a_grafana_notification_is_accepted_and_kept(server, firing) -> None:
    status, _, body = request(server, "POST", body=json.dumps(firing).encode(), **JSON)
    assert (status, body) == (202, {"accepted": 1})
    (incident,) = stored(server)
    assert incident | {"received_at": RECEIVED} == example("incident-firing.json")
    charset = {"Content-Type": "Application/JSON; charset=utf-8"}
    assert request(server, "POST", body=json.dumps(firing).encode(), **charset)[0] == 202


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_only_post_is_allowed(server, method) -> None:
    status, headers, _ = request(server, method)
    assert (status, headers["Allow"]) == (405, "POST")


def test_other_paths_types_and_bodies_are_refused(server, firing) -> None:
    payload = json.dumps(firing).encode()
    assert request(server, "POST", "/", payload, **JSON)[0] == 404
    assert request(server, "POST", "/alerts?debug=1", payload, **JSON)[0] == 404
    assert request(server, "POST", body=payload, **{"Content-Type": "text/plain"})[0] == 415
    assert request(server, "POST", body=payload)[0] == 415  # no Content-Type
    assert request(server, "POST", body=b"{not json", **JSON)[0] == 400
    assert request(server, "POST", body=b"[" * 100_000, **JSON)[0] == 400  # nested too deep
    assert request(server, "POST", body=b"9" * 10_000, **JSON)[0] == 400  # an absurd number
    assert request(server, "POST", body=b'{"version": "1"}', **JSON)[0] == 422
    assert stored(server) == []


def test_a_body_without_a_length_or_over_the_cap_is_never_read(server) -> None:
    chunked = (
        b"POST /alerts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
    )
    assert raw(server, chunked).startswith(b"HTTP/1.0 411")
    too_big = (
        b"POST /alerts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {ar.MAX_BODY + 1}\r\n\r\n".encode()
    )
    assert raw(server, too_big).startswith(b"HTTP/1.0 413")  # answered before any body


def test_a_client_that_stops_sending_is_dropped(server, firing) -> None:
    stalled = (
        b"POST /alerts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Content-Length: 100\r\n\r\n{"
    )
    reply = raw(server, stalled)  # returns once the server gives up on it (Handler.timeout)
    assert not reply.startswith(b"HTTP/1.0 2")
    status, _, _ = request(server, "POST", body=json.dumps(firing).encode(), **JSON)
    assert status == 202  # and the server carries on


def test_only_the_latest_incidents_are_kept(tmp_path) -> None:
    inbox = ar.Inbox(tmp_path / "incidents.jsonl", keep=3)
    inbox.add([{"n": n} for n in range(5)])
    lines = (tmp_path / "incidents.jsonl").read_text().splitlines()
    assert [json.loads(line) for line in lines] == [{"n": 2}, {"n": 3}, {"n": 4}]


def test_the_log_never_holds_a_payload_path_or_header(server, firing, capsys) -> None:
    firing["alerts"][0]["annotations"]["summary"] = CANARY
    request(server, "POST", body=json.dumps(firing).encode(), Authorization=CANARY, **JSON)
    request(server, "POST", f"/{CANARY}?token={CANARY}", b"{}", **JSON)
    request(server, "POST", body=json.dumps({"version": CANARY}).encode(), **JSON)
    raw(server, f"BOGUS {CANARY}\r\n\r\n".encode())
    log = capsys.readouterr().out
    assert "incident: firing 'SpendWise AI Parse Failure Rate High' (local)" in log
    assert "POST (other path) 404" in log and "POST /alerts 422" in log
    assert CANARY not in log


# --- The handoff to the AI on-call responder ----------------------------------------------------


class FakeResponder:
    """Records what the receiver POSTs and answers with a scripted status (the last repeats)."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses) or [202]
        self.requests: list[tuple[str, dict, bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append((self.path, dict(self.headers), body))
                status = outer.statuses.pop(0) if len(outer.statuses) > 1 else outer.statuses[0]
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/incidents"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def responder() -> Iterator[type[FakeResponder]]:
    started: list[FakeResponder] = []

    def start(*statuses: int) -> FakeResponder:
        started.append(FakeResponder(*statuses))
        return started[-1]

    yield start
    for fake in started:
        fake.close()


def incident_for_handoff() -> dict:
    return ar.normalize(json.loads((EXAMPLES / "grafana-firing.json").read_text()), RECEIVED)[0]


def test_an_incident_is_delivered_signed_and_the_responder_can_verify_it(responder, capsys) -> None:
    fake = responder(202)
    incident = incident_for_handoff()
    forwarder = ar.Forwarder(fake.url, SECRET)
    assert forwarder.deliver(incident) is True
    ((path, headers, body),) = fake.requests
    assert path == "/incidents" and headers["Content-Type"] == "application/json"
    assert json.loads(body) == incident  # exactly the normalized incident, nothing else
    verify(SECRET, "POST", path, headers, body, Nonces())  # the responder's own check
    assert "handoff: delivered to the responder (HTTP 202, attempt 1)" in capsys.readouterr().out


def test_a_busy_responder_is_retried_with_a_fresh_signature_each_time(responder, capsys) -> None:
    fake = responder(503, 500, 202)
    pauses: list[float] = []
    forwarder = ar.Forwarder(fake.url, SECRET, sleep=pauses.append)
    assert forwarder.deliver(incident_for_handoff()) is True
    assert len(fake.requests) == 3 and pauses == [1.0, 2.0]
    nonces = {headers["X-SpendWise-Nonce"] for _, headers, _ in fake.requests}
    assert len(nonces) == 3  # a retry is a new request, not a replay
    assert "attempt 3" in capsys.readouterr().out


def test_it_gives_up_after_three_attempts(responder, capsys) -> None:
    fake = responder(503)
    forwarder = ar.Forwarder(fake.url, SECRET, sleep=lambda _: None)
    assert forwarder.deliver(incident_for_handoff()) is False
    assert len(fake.requests) == ar.HANDOFF_ATTEMPTS == 3
    assert "handoff: failed after 3 attempts" in capsys.readouterr().out


@pytest.mark.parametrize("status", [400, 401, 409, 413, 415, 422])
def test_a_refusal_is_final_and_is_not_retried(responder, capsys, status) -> None:
    fake = responder(status)
    forwarder = ar.Forwarder(fake.url, SECRET, sleep=lambda _: None)
    assert forwarder.deliver(incident_for_handoff()) is False
    assert len(fake.requests) == 1
    assert f"handoff: refused by the responder (HTTP {status})" in capsys.readouterr().out


def test_an_unreachable_responder_is_retried_then_given_up_on(capsys) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    forwarder = ar.Forwarder(f"http://127.0.0.1:{port}/incidents", SECRET, sleep=lambda _: None)
    assert forwarder.deliver(incident_for_handoff()) is False
    assert "handoff: failed after 3 attempts" in capsys.readouterr().out


def test_the_log_of_a_handoff_never_holds_the_incident_the_secret_or_a_signature(
    responder, capsys
) -> None:
    fake = responder(503, 202)
    incident = incident_for_handoff() | {"summary": INJECTION}
    ar.Forwarder(fake.url, SECRET, sleep=lambda _: None).deliver(incident)
    printed = capsys.readouterr().out
    headers = fake.requests[0][1]
    for forbidden in (SECRET, INJECTION, headers["X-SpendWise-Signature"], incident["fingerprint"]):
        assert forbidden not in printed


def test_grafana_gets_its_answer_without_waiting_for_the_responder(tmp_path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    forwarder = ar.Forwarder(f"http://127.0.0.1:{port}/incidents", SECRET, sleep=lambda _: None)
    forwarder.start()
    hub = ar.Server(("127.0.0.1", 0), ar.Inbox(tmp_path / "incidents.jsonl"), forwarder)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    try:
        began = time.monotonic()
        connection = http.client.HTTPConnection(*hub.server_address, timeout=5)
        connection.request(
            "POST", "/alerts", body=(EXAMPLES / "grafana-firing.json").read_bytes(), headers=JSON
        )
        assert connection.getresponse().status == 202
        assert time.monotonic() - began < 1
        forwarder.pending.join()
    finally:
        hub.shutdown()
        hub.server_close()
    assert len(hub.inbox.incidents) == 1  # kept whether or not the handoff worked


def test_a_full_handoff_queue_drops_with_a_log_line_instead_of_blocking(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(ar, "HANDOFF_QUEUE", 1)
    forwarder = ar.Forwarder("http://responder:8090/incidents", SECRET)  # never started
    forwarder.submit({"n": 1})
    forwarder.submit({"n": 2})
    assert "handoff: dropped an incident (queue full)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "https://responder:8090/incidents",
        "http://responder/incidents",
        "http://responder:8090/alerts",
        "http://responder:8090/incidents?x=1",
        "http://user:pw@responder:8090/incidents",
        "responder:8090/incidents",
        "",
    ],
)
def test_the_handoff_url_must_be_plain_http_host_port_incidents(url) -> None:
    with pytest.raises(ValueError, match="ONCALL_RESPONDER_URL"):
        ar.Forwarder(url, SECRET)


def test_the_handoff_secret_must_be_long_and_its_value_is_never_in_the_error() -> None:
    with pytest.raises(ValueError) as refused:
        ar.Forwarder("http://responder:8090/incidents", "short-secret")
    assert "at least 32" in str(refused.value) and "short-secret" not in str(refused.value)


def test_the_handoff_is_on_only_when_both_variables_are_set(monkeypatch) -> None:
    for key in ("ONCALL_RESPONDER_URL", "ONCALL_HMAC_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert ar.forwarder_from_env() is None  # without the overlay, the receiver calls nothing
    monkeypatch.setenv("ONCALL_RESPONDER_URL", "http://responder:8090/incidents")
    with pytest.raises(ValueError, match="both"):
        ar.forwarder_from_env()
    monkeypatch.delenv("ONCALL_RESPONDER_URL")
    monkeypatch.setenv("ONCALL_HMAC_SECRET", SECRET)
    with pytest.raises(ValueError, match="both"):
        ar.forwarder_from_env()
    monkeypatch.setenv("ONCALL_RESPONDER_URL", "http://responder:8090/incidents")
    assert isinstance(ar.forwarder_from_env(), ar.Forwarder)


def test_a_misconfigured_receiver_exits_without_printing_the_secret(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ONCALL_RESPONDER_URL", "http://responder:8090/incidents")
    monkeypatch.setenv("ONCALL_HMAC_SECRET", "too-short-secret")
    with pytest.raises(SystemExit) as stopped:
        ar.main()
    assert stopped.value.code == 2
    assert "too-short-secret" not in capsys.readouterr().err


# --- What it can't do ---------------------------------------------------------------------------

SOURCE = ast.parse((RECEIVER_DIR / "alert_receiver.py").read_text())


def test_the_receiver_uses_only_inert_standard_library_modules() -> None:
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(SOURCE)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert imported <= {
        "collections",
        "contextlib",
        "datetime",
        "hashlib",  # the handoff's signature
        "hmac",
        "http.client",  # the handoff's one outbound call (Forwarder.post)
        "http.server",
        "json",
        "math",
        "os",
        "pathlib",
        "queue",  # Grafana never waits for the handoff
        "re",
        "secrets",
        "signal",
        "socket",  # the shutdown constant and annotations only: it never connects
        "socketserver",  # one thread per connection, bounded
        "sys",
        "threading",
        "time",
        "unicodedata",
        "urllib.parse",
    }, imported  # no subprocess, socket clients, urllib.request, pickle, yaml or templates


def test_the_only_outbound_call_is_the_handoff_to_the_responder() -> None:
    classes = {node.name: node for node in SOURCE.body if isinstance(node, ast.ClassDef)}
    inside = {id(n) for n in ast.walk(classes["Forwarder"])}
    users = [
        node
        for node in ast.walk(SOURCE)
        if isinstance(node, ast.Name) and node.id == "http" and id(node) not in inside
    ]
    assert users == []  # http.client is used in Forwarder and nowhere else
    posts = [
        node
        for node in ast.walk(classes["Forwarder"])
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(".request")
    ]
    ((call,),) = [[c] for c in posts]  # one request, and it is a POST to the fixed path
    assert [ast.unparse(a) for a in call.args[:2]] == ["'POST'", "HANDOFF_PATH"]


def test_the_receiver_never_executes_or_evaluates_anything() -> None:
    calls = [node.func for node in ast.walk(SOURCE) if isinstance(node, ast.Call)]
    builtins = {f.id for f in calls if isinstance(f, ast.Name)}
    assert not builtins & {"eval", "exec", "compile", "__import__", "open", "breakpoint"}
    os_calls = {ast.unparse(f) for f in calls if ast.unparse(f).startswith("os.")}
    assert os_calls == {"os.environ.get"}  # no os.system, os.popen, os.exec* or os.spawn*


def test_the_receiver_never_opens_or_accepts_a_socket_itself() -> None:
    calls = {ast.unparse(n.func) for n in ast.walk(SOURCE) if isinstance(n, ast.Call)}
    assert not [call for call in calls if call.startswith(("socket.", "socketserver."))]


# --- Hardening: slow clients, lengths, numbers, the handoff worker ------------------------------

HEAD = (
    b"POST /alerts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
    b"Content-Length: 1000\r\n\r\n"
)


@pytest.fixture
def quick(server, monkeypatch):
    """Short deadlines (after `server`, so its own timeout patch doesn't win)."""
    monkeypatch.setattr(ar, "REQUEST_DEADLINE", 1.0)
    monkeypatch.setattr(ar, "REAP_INTERVAL", 0.1)
    monkeypatch.setattr(ar.Handler, "timeout", 5)  # the per-read timeout alone would wait 5 s


def firing_bytes(**changes) -> bytes:
    payload = example("grafana-firing.json")
    payload["alerts"][0] |= changes
    return json.dumps(payload).encode()


def test_a_stalled_client_does_not_block_other_requests(quick, server) -> None:
    stalled = Stalled(server.server_address, HEAD)
    try:
        began = time.monotonic()
        assert request(server, "POST", body=firing_bytes(), **JSON)[0] == 202
        assert time.monotonic() - began < 0.9
        assert stalled.closed_after(0.05) is None  # the slow one was still open meanwhile
    finally:
        stalled.close()


def test_a_trickle_is_cut_off_by_the_overall_deadline_not_the_read_timeout(
    quick, server, capsys
) -> None:
    stalled = Stalled(server.server_address, HEAD, interval=0.1)  # never trips the 5 s read timeout
    try:
        elapsed = stalled.closed_after(4)
    finally:
        stalled.close()
    assert elapsed is not None and 0.8 < elapsed < 3, elapsed
    assert "request: dropped (open longer than the deadline)" in capsys.readouterr().out


def test_a_trickled_header_is_cut_off_too(quick, server) -> None:
    stalled = Stalled(server.server_address, b"POST /alerts HTTP/1.1\r\nHost: x\r\nX-Slow: ")
    try:
        elapsed = stalled.closed_after(4)
    finally:
        stalled.close()
    assert elapsed is not None and elapsed < 3, elapsed


def test_open_connections_are_capped_and_the_next_is_told_busy_at_once(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(ar, "MAX_CONNECTIONS", 2)
    monkeypatch.setattr(ar, "REQUEST_DEADLINE", 1.5)
    monkeypatch.setattr(ar, "REAP_INTERVAL", 0.1)
    monkeypatch.setattr(ar.Handler, "timeout", 5)
    hub = ar.Server(("127.0.0.1", 0), ar.Inbox(tmp_path / "incidents.jsonl"))
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    held = [Stalled(hub.server_address, HEAD) for _ in range(2)]
    try:
        began = time.monotonic()
        answer = raw_request(hub.server_address, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        assert status_of(answer) == 503 and b'"busy"' in answer
        assert time.monotonic() - began < 1
        assert "request: turned away (too many open connections)" in capsys.readouterr().out
        assert all(client.closed_after(4) is not None for client in held)
        for _ in range(40):  # the slot is freed a moment after the client sees the close
            reply = raw_request(hub.server_address, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            if status_of(reply) != 503:
                break
            time.sleep(0.05)
        assert status_of(reply) == 405  # served normally again
    finally:
        for client in held:
            client.close()
        hub.shutdown()
        hub.server_close()


def test_concurrent_posts_leave_the_incident_file_intact(server, tmp_path) -> None:
    gate = threading.Barrier(12)
    statuses: list[int] = []

    def send(number: int) -> None:
        gate.wait()
        body = firing_bytes(fingerprint=f"{number:016x}")
        statuses.append(request(server, "POST", body=body, **JSON)[0])

    threads = [threading.Thread(target=send, args=(n,)) for n in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert statuses == [202] * 12
    lines = server.inbox.path.read_text().splitlines()
    assert len(lines) == 12 and len({json.loads(line)["fingerprint"] for line in lines}) == 12
    assert not server.inbox.path.with_suffix(".partial").exists()


def test_nothing_is_printed_to_stderr_when_clients_misbehave(quick, server, capsys) -> None:
    stalled = Stalled(server.server_address, HEAD)
    raw_request(server.server_address, b"POST /alerts HTTP/1.1\r\nContent-Length: \xb2\r\n\r\n")
    raw_request(server.server_address, b"\x00\x01 not http at all\r\n\r\n")
    assert stalled.closed_after(4) is not None
    stalled.close()
    assert capsys.readouterr().err == ""


def length_request(value: bytes) -> bytes:
    return (
        b"POST /alerts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Content-Length: " + value + b"\r\n\r\n{}"
    )


@pytest.mark.parametrize(
    "length",
    [b"\xb2", b"\xb3", b"\xb9", b"+5", b"-1", b"1e3", b"0x10", b"12 34", b"1,2", b"9" * 20]
    + [b"1" * 5000, b""],
)
def test_a_content_length_that_is_not_ascii_digits_is_a_400_not_a_dropped_connection(
    server, capsys, length
) -> None:
    answer = raw(server, length_request(length))
    assert status_of(answer) == 400 and b'"invalid Content-Length"' in answer
    assert capsys.readouterr().err == ""
    assert request(server, "POST", body=firing_bytes(), **JSON)[0] == 202  # the server is fine


def test_two_content_lengths_are_refused(server) -> None:
    both = (
        b"POST /alerts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}"
    )
    assert status_of(raw(server, both)) == 400


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10**400, None),
        (-(10**400), None),
        (10**16, None),
        (float("inf"), None),
        (float("-inf"), None),
        (float("nan"), None),
        (True, None),
        ("0.5", None),
        (None, None),
        (10**15, 1e15),
        (0, 0.0),
        (3, 3.0),
        (0.1234567, 0.123457),
    ],
)
def test_a_number_that_is_not_a_measurement_is_none_and_never_an_exception(value, expected) -> None:
    assert ar.number(value) == expected


@pytest.mark.parametrize("value", [10**400, "1e999"])
def test_a_huge_value_in_a_payload_is_stored_as_null_not_a_dropped_connection(
    server, capsys, value
) -> None:
    body = firing_bytes(values={"A": value}).replace(b'"1e999"', b"1e999")  # 1e999 parses as inf
    status, _, answer = request(server, "POST", body=body, **JSON)
    assert (status, answer) == (202, {"accepted": 1})
    assert stored(server)[-1]["value"] is None
    assert capsys.readouterr().err == ""


def test_an_unexpected_error_costs_one_request_and_is_answered(server, monkeypatch, capsys) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("secret detail that must not be logged")

    monkeypatch.setattr(ar, "normalize", broken)
    status, _, answer = request(server, "POST", body=firing_bytes(), **JSON)
    assert (status, answer) == (500, {"error": "internal error"})
    printed = capsys.readouterr()
    assert "request failed (RuntimeError)" in printed.out and "secret detail" not in printed.out
    assert printed.err == ""
    monkeypatch.undo()
    assert request(server, "POST", body=firing_bytes(), **JSON)[0] == 202


def test_an_unexpected_error_does_not_end_the_handoff(responder, capsys) -> None:
    fake = responder(202)
    forwarder = ar.Forwarder(fake.url, SECRET, sleep=lambda _: None)
    real_post, calls = forwarder.post, []

    def flaky(body: bytes):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError(f"boom {INJECTION} {SECRET}")  # not an OSError: not expected
        return real_post(body)

    forwarder.post = flaky
    forwarder.start()
    first = incident_for_handoff()
    forwarder.submit(first)
    forwarder.submit(first | {"fingerprint": "00000000000000bb"})
    forwarder.pending.join()
    assert len(fake.requests) == 1  # the second incident was delivered after the first one blew up
    assert json.loads(fake.requests[0][2])["fingerprint"] == "00000000000000bb"
    printed = capsys.readouterr().out
    assert "handoff: failed unexpectedly (ValueError)" in printed
    assert "boom" not in printed and SECRET not in printed and "IGNORE" not in printed
    assert any(t.name == "handoff" and t.is_alive() for t in threading.enumerate())
