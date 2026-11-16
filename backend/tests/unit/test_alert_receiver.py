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
from collections.abc import Iterator
from pathlib import Path

import pytest

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
        "datetime",
        "http.server",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "signal",
        "sys",
        "unicodedata",
        "urllib.parse",
    }, imported  # no subprocess, socket clients, urllib.request, pickle, yaml or templates


def test_the_receiver_never_executes_or_evaluates_anything() -> None:
    calls = [node.func for node in ast.walk(SOURCE) if isinstance(node, ast.Call)]
    builtins = {f.id for f in calls if isinstance(f, ast.Name)}
    assert not builtins & {"eval", "exec", "compile", "__import__", "open", "breakpoint"}
    os_calls = {ast.unparse(f) for f in calls if ast.unparse(f).startswith("os.")}
    assert os_calls == {"os.environ.get"}  # no os.system, os.popen, os.exec* or os.spawn*
