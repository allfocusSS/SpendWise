"""The responder's HTTP server, its configuration, and the whole chain in one process.

Real sockets on loopback: a signed POST /incidents is checked in a fixed order, queued, and turned
into a report by the worker. The last test runs Grafana's real webhook payload through the real
alert receiver (which signs and forwards it) into the real responder.
"""

import http.client
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from oncall_responder import report as rp
from oncall_responder import server as srv
from oncall_responder.model import FakeModel
from oncall_responder.settings import Settings, SettingsError
from oncall_responder.signing import H_NONCE, H_SIGNATURE, H_TIMESTAMP, Nonces, sign
from oncall_responder.store import ReportStore
from oncall_support import (
    EXAMPLES,
    GRAFANA,
    INJECTION,
    SECRET,
    FakeBackends,
    Scripted,
    Stalled,
    incident_json,
    raw_request,
    status_of,
    valid_answer,
)

RECEIVER = Path(__file__).resolve().parents[3] / "deploy/observability/alert-receiver"
JSON = {"Content-Type": "application/json"}


class Responder:
    def __init__(self, server: srv.Server, audit: list[str], store: ReportStore) -> None:
        self.server, self.audit, self.store = server, audit, store

    @property
    def address(self):
        return self.server.server_address

    def post(self, body=None, headers=None, path="/incidents", method="POST", signed=True):
        body = json.dumps(incident_json()).encode() if body is None else body
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        merged = dict(JSON)
        if signed:
            merged |= sign(SECRET, "POST", "/incidents", body)
        merged |= headers or {}
        connection = http.client.HTTPConnection(*self.address, timeout=5)
        connection.request(method, path, body=body if method != "GET" else None, headers=merged)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if data else {}

    def idle(self) -> None:
        self.server.pending.join()

    def reports(self) -> list[dict]:
        return list(self.store.reports.values())


def build(tmp_path, model=None, worker=True, backends=None) -> Responder:
    settings = Settings(
        secret=SECRET,
        model="fake",
        prometheus_url="http://lgtm:9090",
        loki_url="http://lgtm:3100",
        tempo_url="http://lgtm:3200",
        grafana_origin=GRAFANA,
        reports_file=tmp_path / "reports.jsonl",
    )
    audit: list[str] = []
    store = ReportStore(settings.reports_file)
    server = srv.Server(
        ("127.0.0.1", 0),
        settings,
        backends or FakeBackends("ai"),
        model or FakeModel(),
        store,
        audit=audit.append,
    )
    if worker:
        server.start_worker()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return Responder(server, audit, store)


@pytest.fixture
def responder(tmp_path, monkeypatch):
    monkeypatch.setattr(srv.Handler, "timeout", 1)
    running = build(tmp_path)
    yield running
    running.server.shutdown()
    running.server.server_close()


@pytest.fixture
def stopped(tmp_path, monkeypatch):
    """A responder whose worker never runs, so queued incidents stay queued."""
    monkeypatch.setattr(srv.Handler, "timeout", 1)
    running = build(tmp_path, worker=False)
    yield running
    running.server.shutdown()
    running.server.server_close()


# --- Accepting an incident ---------------------------------------------------------------------


def test_a_signed_incident_is_accepted_and_becomes_a_report(responder) -> None:
    status, body = responder.post()
    assert status == 202 and body["accepted"] is True and len(body["report_id"]) == 16
    responder.idle()
    (report,) = responder.reports()
    assert report["report_id"] == body["report_id"]
    assert rp.validate_report(report, (SECRET,)) == []
    assert report["handoff"] == {"authenticated": True, "scheme": "hmac-sha256-v1"}
    assert len(responder.store.path.read_text().splitlines()) == 1
    assert f"handoff: accepted {body['report_id']} (signature ok)" in responder.audit
    assert any(line.startswith("report: stored") for line in responder.audit)


def test_the_request_does_not_wait_for_the_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(srv.Handler, "timeout", 1)
    release, started = threading.Event(), threading.Event()

    class Slow(Scripted):
        def complete(self, system, user):
            started.set()
            release.wait(10)
            return super().complete(system, user)

    running = build(tmp_path, model=Slow(valid_answer()))
    try:
        began = time.monotonic()
        assert running.post()[0] == 202
        assert time.monotonic() - began < 2  # answered while the model hasn't even finished
        assert started.wait(5) and running.reports() == []
        release.set()
        running.idle()
        assert len(running.reports()) == 1
    finally:
        release.set()
        running.server.shutdown()
        running.server.server_close()


def test_the_same_incident_twice_is_one_report(responder) -> None:
    assert responder.post()[0] == 202 and responder.post()[0] == 202  # two nonces, one incident
    responder.idle()
    assert len(responder.reports()) == 1


def test_a_failing_incident_does_not_stop_the_worker(responder, monkeypatch) -> None:
    real = srv.respond
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(srv, "respond", flaky)
    assert responder.post(incident_json(fingerprint="00000000000000aa"))[0] == 202
    responder.idle()
    assert responder.reports() == [] and "report: failed (RuntimeError)" in responder.audit
    assert responder.post(incident_json(fingerprint="00000000000000bb"))[0] == 202
    responder.idle()
    assert len(responder.reports()) == 1


# --- Refusing what isn't authentic or isn't an incident ----------------------------------------


def test_an_unsigned_request_is_refused_without_looking_at_it(responder) -> None:
    status, body = responder.post(signed=False)
    assert (status, body) == (401, {"error": "unauthorized"})
    assert "handoff: refused (missing-or-malformed-headers)" in responder.audit
    responder.idle()
    assert responder.reports() == []


def test_a_bad_signature_is_refused_and_the_answer_does_not_say_why(responder) -> None:
    body = json.dumps(incident_json()).encode()
    forged = sign("another-secret-" + "x" * 32, "POST", "/incidents", body)
    assert responder.post(body, forged, signed=False) == (401, {"error": "unauthorized"})
    tampered = sign(SECRET, "POST", "/incidents", body)
    assert responder.post(body + b" ", tampered, signed=False)[0] == 401
    assert "handoff: refused (bad-signature)" in responder.audit


def test_a_stale_timestamp_is_refused(responder) -> None:
    body = json.dumps(incident_json()).encode()
    old = sign(SECRET, "POST", "/incidents", body, timestamp=int(time.time()) - 301)
    assert responder.post(body, old, signed=False)[0] == 401
    assert "handoff: refused (stale-timestamp)" in responder.audit


def test_a_replayed_request_is_refused(responder) -> None:
    body = json.dumps(incident_json()).encode()
    headers = sign(SECRET, "POST", "/incidents", body)
    assert responder.post(body, headers, signed=False)[0] == 202
    assert responder.post(body, headers, signed=False) == (409, {"error": "replay"})
    assert "handoff: refused (replay)" in responder.audit
    responder.idle()
    assert len(responder.reports()) == 1


def test_a_forged_request_cannot_burn_a_genuine_nonce(responder) -> None:
    body = json.dumps(incident_json()).encode()
    genuine = sign(SECRET, "POST", "/incidents", body)
    forged = genuine | {H_SIGNATURE: "v1=" + "0" * 64}
    assert responder.post(body, forged, signed=False)[0] == 401
    assert responder.post(body, genuine, signed=False)[0] == 202


def test_too_many_recent_requests_are_refused_not_forgotten(responder) -> None:
    responder.server.nonces = Nonces(limit=2)
    assert [responder.post()[0] for _ in range(3)] == [202, 202, 503]
    assert "handoff: refused (too many recent requests)" in responder.audit


def test_a_full_queue_refuses_with_503(stopped) -> None:
    statuses = [
        stopped.post(incident_json(fingerprint=f"{n:016x}"))[0] for n in range(srv.QUEUE + 2)
    ]
    assert statuses == [202] * srv.QUEUE + [503, 503]
    assert "handoff: refused (queue full)" in stopped.audit


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"labels": {"x": 1}}, 422),
        ({"status": "exploded"}, 422),
        ({"category": "billing"}, 422),
        ({"environment": 'x"}'}, 422),
        ({"fingerprint": None}, 422),
    ],
)
def test_a_signed_body_outside_the_contract_is_refused_with_the_rule_not_the_value(
    responder, overrides, status
) -> None:
    code, body = responder.post(incident_json(**overrides))
    assert code == status and "error" in body
    assert INJECTION not in json.dumps(body) and 'x"}' not in json.dumps(body)


def test_malformed_json_that_is_signed_is_a_400(responder) -> None:
    assert responder.post(b"{not json") == (400, {"error": "malformed JSON"})
    assert responder.post(b"[" * 5000) == (400, {"error": "malformed JSON"})  # nested too deep


def test_a_document_too_deep_to_parse_is_a_400_not_a_crash(responder, monkeypatch) -> None:
    def too_deep(*args, **kwargs):
        raise RecursionError

    real = srv.parse_incident
    monkeypatch.setattr(srv, "parse_incident", too_deep)
    assert responder.post() == (400, {"error": "malformed JSON"})
    monkeypatch.setattr(srv, "parse_incident", real)
    deep = b"[" * 8000 + b"]" * 8000  # inside the size cap, nested far past any incident
    assert responder.post(deep)[0] in (400, 422)
    assert responder.post()[0] == 202  # the server carries on


def test_other_methods_paths_types_and_sizes_are_refused(responder) -> None:
    assert responder.post(path="/incidents/", signed=True)[0] == 404
    assert responder.post(path="/alerts")[0] == 404
    assert responder.post(path="/incidents?debug=1")[0] == 404
    for method in ("GET", "PUT", "DELETE", "PATCH", "OPTIONS"):
        status, body = responder.post(method=method, body=b"")
        assert (status, body) == (405, {"error": "POST only"})
    assert responder.post(headers={"Content-Type": "text/plain"})[0] == 415
    big = b" " * (srv.MAX_BODY + 1)
    assert responder.post(big, headers={})[0] == 413
    responder.idle()
    assert responder.reports() == []


def test_a_request_without_a_length_or_that_stops_sending_is_dropped(responder) -> None:
    import socket

    def raw(data: bytes) -> bytes:
        with socket.create_connection(responder.address, timeout=5) as sock:
            sock.sendall(data)
            chunks = []
            while chunk := sock.recv(65536):
                chunks.append(chunk)
        return b"".join(chunks)

    chunked = (
        b"POST /incidents HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n"
    )
    assert raw(chunked).startswith(b"HTTP/1.0 411")
    stalled = (
        b"POST /incidents HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Content-Length: 100\r\n\r\n{"
    )
    assert not raw(stalled).startswith(b"HTTP/1.0 2")
    assert responder.post()[0] == 202  # and the server carries on


def test_logs_hold_decisions_never_payloads_headers_or_secrets(responder, capsys) -> None:
    body = json.dumps(incident_json(summary=INJECTION)).encode()
    headers = sign(SECRET, "POST", "/incidents", body)
    responder.post(body, headers, signed=False)
    responder.post(body, headers, signed=False)  # replay
    responder.post(incident_json(status="exploded"))
    responder.post(signed=False, headers={"Authorization": "Bearer abcdefghijklmnop1234"})
    responder.idle()
    printed = capsys.readouterr().out + "\n".join(responder.audit)
    for forbidden in (
        SECRET,
        headers[H_SIGNATURE],
        headers[H_NONCE],
        headers[H_TIMESTAMP],
        "IGNORE",
        "evil.test",
        "abcdefghijklmnop1234",
        "a7edbaa05b9b86b7",
    ):
        assert forbidden not in printed, forbidden


# --- Configuration -----------------------------------------------------------------------------

ENV = {
    "ONCALL_HMAC_SECRET": SECRET,
    "PROMETHEUS_URL": "http://lgtm:9090",
    "LOKI_URL": "http://lgtm:3100",
    "TEMPO_URL": "http://lgtm:3200",
}


def test_settings_come_from_the_environment_with_safe_defaults() -> None:
    settings = Settings.from_env(ENV)
    assert settings.model == "fake" and settings.grafana_origin is None
    assert settings.reports_file == Path("/var/lib/oncall/reports.jsonl")
    assert settings.secrets == (SECRET,)
    with_origin = Settings.from_env(
        ENV | {"ONCALL_GRAFANA_ORIGIN": GRAFANA, "ONCALL_REPORTS": "/x/r"}
    )
    assert with_origin.grafana_origin == GRAFANA and with_origin.reports_file == Path("/x/r")


@pytest.mark.parametrize(
    "change",
    [
        {"ONCALL_HMAC_SECRET": ""},
        {"ONCALL_HMAC_SECRET": "short"},
        {"ONCALL_HMAC_SECRET": "x" * 31},
        {"ONCALL_MODEL": "anthropic"},
        {"ONCALL_MODEL": ""},
        {"PROMETHEUS_URL": ""},
        {"LOKI_URL": "https://lgtm:3100"},
        {"TEMPO_URL": "http://lgtm:3200/api"},
        {"TEMPO_URL": "http://user:pw@lgtm:3200"},
        {"ONCALL_GRAFANA_ORIGIN": "http://127.0.0.1:3000/d/x"},
        {"ONCALL_GRAFANA_ORIGIN": "javascript:alert(1)"},
    ],
)
def test_a_bad_setting_is_refused_without_echoing_its_value(change) -> None:
    with pytest.raises(SettingsError) as refused:
        Settings.from_env(ENV | change)
    message = str(refused.value)
    assert all(str(value) not in message for value in change.values() if len(str(value)) > 4)


def test_there_is_no_default_secret() -> None:
    env = dict(ENV)
    del env["ONCALL_HMAC_SECRET"]
    with pytest.raises(SettingsError, match="ONCALL_HMAC_SECRET must be set"):
        Settings.from_env(env)


def test_a_misconfigured_responder_exits_before_listening(monkeypatch, capsys) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit) as stopped:
        srv.main()
    assert stopped.value.code == 2
    assert "configuration error" in capsys.readouterr().err


# --- The whole chain, in one process -----------------------------------------------------------


def load_receiver():
    spec = importlib.util.spec_from_file_location(
        "alert_receiver_chain", RECEIVER / "alert_receiver.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_grafanas_real_payload_goes_through_the_receiver_to_a_report(tmp_path, monkeypatch) -> None:
    receiver = load_receiver()
    monkeypatch.setattr(srv.Handler, "timeout", 1)
    responder = build(tmp_path)
    host, port = responder.address
    forwarder = receiver.Forwarder(f"http://{host}:{port}/incidents", SECRET)
    forwarder.start()
    inbox = receiver.Inbox(tmp_path / "incidents.jsonl")
    hub = receiver.Server(("127.0.0.1", 0), inbox, forwarder)
    threading.Thread(target=hub.serve_forever, daemon=True).start()
    try:
        payload = (EXAMPLES / "grafana-firing.json").read_bytes()
        connection = http.client.HTTPConnection(*hub.server_address, timeout=5)
        connection.request("POST", "/alerts", body=payload, headers=JSON)
        assert connection.getresponse().status == 202
        forwarder.pending.join()
        responder.idle()
    finally:
        hub.shutdown()
        hub.server_close()
        responder.server.shutdown()
        responder.server.server_close()
    (incident,) = inbox.incidents
    (report,) = responder.reports()
    assert report["incident"]["fingerprint"] == incident["fingerprint"] == "a7edbaa05b9b86b7"
    assert report["incident"]["alert"] == incident["alert"]
    assert report["handoff"]["authenticated"] is True
    assert rp.validate_report(report, (SECRET,)) == []
    assert "handoff: accepted" in responder.audit[0]


# --- One slow client must not hold up the rest -------------------------------------------------

HEAD = (
    b"POST /incidents HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
    b"Content-Length: 1000\r\n\r\n"
)


@pytest.fixture
def quick(monkeypatch):
    """Short deadlines, so the deadline tests take a second or two instead of ten."""
    monkeypatch.setattr(srv, "REQUEST_DEADLINE", 1.0)
    monkeypatch.setattr(srv, "REAP_INTERVAL", 0.1)
    monkeypatch.setattr(srv.Handler, "timeout", 5)  # the per-read timeout alone would wait 5 s


def test_a_stalled_client_does_not_block_other_requests(quick, responder) -> None:
    stalled = Stalled(responder.address, HEAD)
    try:
        began = time.monotonic()
        assert responder.post()[0] == 202  # served while the other connection is still open
        assert time.monotonic() - began < 0.9
        assert stalled.closed_after(0.05) is None  # and it really was still open then
    finally:
        stalled.close()


def test_a_trickle_is_cut_off_at_the_overall_deadline_not_the_read_timeout(
    quick, responder
) -> None:
    # One byte every 0.1 s never trips the 5 s read timeout; only the overall deadline ends it.
    stalled = Stalled(responder.address, HEAD, interval=0.1)
    try:
        elapsed = stalled.closed_after(4)
    finally:
        stalled.close()
    assert elapsed is not None and 0.8 < elapsed < 3, elapsed
    assert "request: dropped (open longer than the deadline)" in responder.audit


def test_a_trickled_header_is_cut_off_too(quick, responder) -> None:
    stalled = Stalled(responder.address, b"POST /incidents HTTP/1.1\r\nHost: x\r\nX-Slow: ")
    try:
        elapsed = stalled.closed_after(4)
    finally:
        stalled.close()
    assert elapsed is not None and elapsed < 3, elapsed


def test_open_connections_are_capped_and_the_next_is_told_busy_at_once(
    quick, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(srv, "MAX_CONNECTIONS", 2)
    monkeypatch.setattr(srv, "REQUEST_DEADLINE", 1.5)
    running = build(tmp_path)
    held = [Stalled(running.address, HEAD) for _ in range(2)]
    try:
        began = time.monotonic()
        answer = raw_request(running.address, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        assert status_of(answer) == 503 and b'"busy"' in answer
        assert time.monotonic() - began < 1  # not queued behind the two that are stalled
        assert "request: turned away (too many open connections)" in running.audit
        # Once the stalled ones are cut off, the slots are free again.
        assert all(client.closed_after(4) is not None for client in held)
        for _ in range(40):  # the slot is freed a moment after the client sees the close
            if (status := running.post()[0]) != 503:
                break
            time.sleep(0.05)
        assert status == 202
    finally:
        for client in held:
            client.close()
        running.server.shutdown()
        running.server.server_close()


def test_the_same_signed_request_sent_at_once_is_accepted_exactly_once(responder) -> None:
    body = json.dumps(incident_json()).encode()
    headers = {"Content-Type": "application/json"} | sign(SECRET, "POST", "/incidents", body)
    statuses: list[int] = []
    gate = threading.Barrier(12)

    def send() -> None:
        gate.wait()
        statuses.append(responder.post(body, headers, signed=False)[0])

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # make thread switches as likely as possible
    try:
        threads = [threading.Thread(target=send) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(old)
    assert sorted(statuses) == [202] + [409] * 11  # one first, eleven replays: never two firsts


def test_the_nonce_store_never_lets_two_threads_both_be_first() -> None:
    from oncall_responder.signing import Replayed

    nonces, outcomes = Nonces(), []
    gate = threading.Barrier(32)

    def claim() -> None:
        gate.wait()
        try:
            nonces.remember("ab" * 16, int(time.time()), time.time())
            outcomes.append("first")
        except Replayed:
            outcomes.append("replay")

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=claim) for _ in range(32)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        sys.setswitchinterval(old)
    assert outcomes.count("first") == 1 and outcomes.count("replay") == 31


def test_nothing_is_printed_to_stderr_when_clients_misbehave(quick, responder, capsys) -> None:
    stalled = Stalled(responder.address, HEAD)
    raw_request(responder.address, b"POST /incidents HTTP/1.1\r\nContent-Length: \xb2\r\n\r\n")
    raw_request(responder.address, b"\x00\x01 not http at all\r\n\r\n")
    assert stalled.closed_after(4) is not None
    stalled.close()
    assert capsys.readouterr().err == ""  # no tracebacks, no client addresses


def test_an_unexpected_error_costs_one_request_and_is_answered(responder, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("secret detail that must not be logged")

    monkeypatch.setattr(srv, "parse_incident", broken)
    assert responder.post() == (500, {"error": "internal error"})
    assert "request failed (RuntimeError)" in responder.audit
    assert all("secret detail" not in line for line in responder.audit)
    monkeypatch.undo()
    assert responder.post()[0] == 202  # and the server carries on


# --- Content-Length, numbers and error text ----------------------------------------------------


def with_length(value: bytes) -> bytes:
    return (
        b"POST /incidents HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Content-Length: " + value + b"\r\n\r\n{}"
    )


@pytest.mark.parametrize(
    "length",
    [
        b"\xb2",  # superscript two: str.isdigit() is true, int() refuses it
        b"\xb3",
        b"\xb9",
        b"+5",
        b"-1",
        b"1e3",
        b"0x10",
        b"12 34",
        b"1,2",
        b"9" * 20,  # more digits than any body
        b"1" * 5000,  # more digits than int() will read
        b"",
    ],
)
def test_a_content_length_that_is_not_ascii_digits_is_a_400_not_a_dropped_connection(
    responder, capsys, length
) -> None:
    answer = raw_request(responder.address, with_length(length))
    assert status_of(answer) == 400 and b'"invalid Content-Length"' in answer
    assert capsys.readouterr().err == "" and responder.post()[0] == 202  # the server is fine


def test_two_content_lengths_are_refused(responder) -> None:
    request = (
        b"POST /incidents HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}"
    )
    assert status_of(raw_request(responder.address, request)) == 400


def test_a_missing_content_length_is_still_a_411(responder) -> None:
    request = b"POST /incidents HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n\r\n"
    assert status_of(raw_request(responder.address, request)) == 411


@pytest.mark.parametrize(
    "value",
    [
        10**400,
        -(10**400),
        10**16,
        -(10**16),
        float("inf"),
        float("-inf"),
        float("nan"),
        "0.5",
        True,
    ],
)
def test_a_value_that_is_not_a_measurement_is_a_422_not_a_dropped_connection(
    responder, capsys, value
) -> None:
    status, body = responder.post(incident_json(value=value))
    assert (status, body) == (422, {"error": "value is not a finite number"})
    assert "handoff: refused (value is not a finite number)" in responder.audit
    assert capsys.readouterr().err == "" and responder.post()[0] == 202


@pytest.mark.parametrize("value", [0, 1, -3, 0.5, 12345.678, 10**15, None])
def test_ordinary_numbers_and_null_are_accepted(responder, value) -> None:
    assert responder.post(incident_json(value=value))[0] == 202


def test_a_sender_chosen_field_name_is_never_echoed_or_logged(responder) -> None:
    hostile = "A" * 3000 + "\nFAKE LOG LINE " + INJECTION
    status, body = responder.post(incident_json(**{hostile: 1, "labels": {"x": 1}}))
    assert status == 422
    assert body == {"error": "fields differ from the contract (missing [], 2 extra)"}
    logged = "\n".join(responder.audit)
    assert "FAKE LOG LINE" not in logged and "IGNORE" not in logged and "AAAA" not in logged
    assert max(len(line) for line in responder.audit) < 200  # bounded, whatever was sent
    missing = incident_json()
    del missing["runbook"]
    assert responder.post(missing)[1]["error"].endswith("(missing ['runbook'], 0 extra)")
