"""The responder's HTTP server: POST /incidents, signed, and nothing else.

Each request is checked in this order, and the first failure answers:
  path and method → content type → length (digits only, at most 16 KiB) → body → signature,
  timestamp, replay (signing.py) → JSON → the incident contract (incident.py).
Only then is the incident queued for the worker thread, which collects evidence and writes the
report; the request itself never waits for a backend or a model. Logs say what was decided
(a status or a rule's code), never what was sent.

One slow client must not hold up the rest. Every connection gets its own thread, at most
MAX_CONNECTIONS at a time (the next is answered 503 at once, never queued), and a reaper thread
cuts off any connection still open REQUEST_DEADLINE seconds after it was accepted, however slowly
its headers or body arrive. READ_TIMEOUT alone could not do that: it restarts on every byte.
"""

import contextlib
import json
import queue
import re
import signal
import socket
import socketserver
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from oncall_responder.evidence import Backends, HttpBackends
from oncall_responder.incident import Incident, InvalidIncident, parse_incident
from oncall_responder.model import Model, ModelUnavailable, build_model
from oncall_responder.pipeline import ReportInvalid, respond
from oncall_responder.settings import Settings, SettingsError
from oncall_responder.signing import Nonces, Overloaded, Replayed, Unauthorized, verify
from oncall_responder.store import ReportStore, ReportTooLarge

PATH = "/incidents"
PORT = 8090
MAX_BODY = 16 * 1024
READ_TIMEOUT = 5  # seconds a client may stay silent between two reads
REQUEST_DEADLINE = 10  # seconds for a whole request, headers and body, however it trickles in
MAX_CONNECTIONS = 16  # open at once; a thread each, so this also bounds the container's threads
REAP_INTERVAL = 0.5  # how often the reaper looks for connections past their deadline
QUEUE = 20
LENGTH = re.compile(r"[0-9]{1,9}")  # ASCII digits: "²", "١٢" and " 5" are not lengths


_LOG = threading.Lock()


def log(message: str) -> None:
    """One line, written whole: handler threads log concurrently and lines must not be mixed."""
    line = f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} {message}\n"
    with _LOG:
        sys.stdout.write(line)
        sys.stdout.flush()


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    request_queue_size = 32  # a burst of connections waits in the kernel, not reset by it

    def __init__(
        self,
        address: tuple[str, int],
        settings: Settings,
        backends: Backends,
        model: Model,
        store: ReportStore,
        audit=log,
    ) -> None:
        super().__init__(address, Handler)
        self.settings = settings
        self.backends = backends
        self.model = model
        self.store = store
        self.audit = audit
        self.nonces = Nonces()  # locked inside: handler threads share it
        self.pending: queue.Queue[Incident] = queue.Queue(maxsize=QUEUE)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.deadlines: dict[socket.socket, float] = {}  # open connection → monotonic deadline
        self.lock = threading.Lock()  # guards `deadlines`, and the reaper's use of its sockets
        self.closing = threading.Event()
        self.last_turned_away = 0.0
        threading.Thread(target=self.reap, daemon=True, name="responder-reaper").start()

    # --- Bounded concurrency and the overall deadline ------------------------------------------

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
            self.audit("request: turned away (too many open connections)")  # before the answer
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
                    self.audit("request: dropped (open longer than the deadline)")  # then cut
                    with contextlib.suppress(OSError):  # wakes the thread blocked reading it
                        connection.shutdown(socket.SHUT_RDWR)

    def handle_error(self, request, client_address) -> None:
        # The class only: socketserver's default prints a traceback with the client's address.
        self.audit(f"request failed ({type(sys.exc_info()[1]).__name__})")

    def server_close(self) -> None:
        self.closing.set()
        super().server_close()

    # --- The worker ----------------------------------------------------------------------------

    def start_worker(self) -> threading.Thread:
        worker = threading.Thread(target=self.work, daemon=True, name="responder-worker")
        worker.start()
        return worker

    def work(self) -> None:
        while True:
            incident = self.pending.get()
            try:
                report = respond(
                    incident, self.backends, self.model, self.settings.secrets, self.audit
                )
                self.store.put(report)
                self.audit(
                    f"report: stored {report['report_id']} ({incident.status}, "
                    f"{incident.category}, confidence {report['confidence']}, "
                    f"escalation {str(report['escalation_required']).lower()})"
                )
            except (ReportInvalid, ReportTooLarge) as error:
                self.audit(f"report: not stored ({type(error).__name__})")
            except Exception as error:  # the worker must outlive any one incident
                self.audit(f"report: failed ({type(error).__name__})")
            finally:
                self.pending.task_done()


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "spendwise-oncall-responder"
    sys_version = ""
    timeout = READ_TIMEOUT

    def handle(self) -> None:
        # A client that goes away, or one the reaper cut off at the deadline, is not an error.
        with contextlib.suppress(OSError):
            super().handle()

    def do_POST(self) -> None:
        try:
            self.accept_incident()
        except OSError:
            raise  # the connection is gone: handle() lets it go quietly
        except Exception as error:  # a bug costs this one request, with an answer, not a reset
            self.server.audit(f"request failed ({type(error).__name__})")
            self.reply(500, error="internal error")

    def accept_incident(self) -> None:
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
        settings = self.server.settings
        try:
            verify(
                settings.secret, "POST", PATH, self.headers, body, self.server.nonces, time.time()
            )
        except Unauthorized as refused:
            self.server.audit(f"handoff: refused ({refused.code})")
            return self.reply(401, error="unauthorized")
        except Replayed:
            self.server.audit("handoff: refused (replay)")
            return self.reply(409, error="replay")
        except Overloaded:
            self.server.audit("handoff: refused (too many recent requests)")
            return self.reply(503, error="busy")
        try:
            incident = parse_incident(json.loads(body), settings.grafana_origin, settings.secrets)
        except (ValueError, RecursionError) as invalid:
            reason = str(invalid) if isinstance(invalid, InvalidIncident) else "malformed JSON"
            self.server.audit(f"handoff: refused ({reason})")
            return self.reply(400 if reason == "malformed JSON" else 422, error=reason)
        try:
            self.server.pending.put_nowait(incident)
        except queue.Full:
            self.server.audit("handoff: refused (queue full)")
            return self.reply(503, error="busy")
        self.server.audit(f"handoff: accepted {incident.report_id} (signature ok)")
        self.reply(202, accepted=True, report_id=incident.report_id)

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


def main() -> None:
    try:
        settings = Settings.from_env()
        model = build_model(settings.model)
        backends = HttpBackends(settings.prometheus_url, settings.loki_url, settings.tempo_url)
    except (SettingsError, ModelUnavailable, ValueError) as error:
        print(f"configuration error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    server = Server(
        ("0.0.0.0", PORT), settings, backends, model, ReportStore(settings.reports_file)
    )
    server.start_worker()
    log(f"listening on :{PORT}{PATH} (model {model.provider})")
    server.serve_forever()
