"""Bounded, read-only evidence from Prometheus, Loki and Tempo.

Trusted code chooses every query. Each one is a fixed template in QUERIES, picked by the
incident's category; the only thing substituted into it is the incident's environment, which the
incident validator already restricted to [a-z0-9-]. Nothing a model, a log line or an alert
annotation says can reach a query, a URL or a trace ID.

Bounds: five series per Prometheus query, a 15-minute window and 20 lines for Loki, five traces
for Tempo, 256 KiB and 5 s per response, 25 s for everything. A backend that fails or answers
oddly costs only its own evidence, and is named in the report's limitations.

Log text is counted, not quoted: the model sees a log line only if it is exactly one of the app's
own message shapes (LOG_MESSAGES), and the report never holds a log line at all.

The access is GET-only through `HttpBackends`, which has no method that takes a URL, a host or a
verb: three fixed base URLs from the environment, three fixed API paths.
"""

import http.client
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from oncall_responder.incident import NAME, Incident
from oncall_responder.privacy import safe_text

WINDOW = 900  # seconds of logs and traces
LOKI_LIMIT = 20
MAX_SERIES = 5
MAX_TRACES = 5
MAX_SAMPLES = 5  # recognised log lines in the prompt (never in the report)
MAX_RESPONSE = 256 * 1024
TIMEOUT = 5.0
DEADLINE = 25.0

SELECTOR = 'service_name="spendwise-api", deployment_environment_name="@ENV@"'
LOG_STREAM = '{service_name="spendwise-api", deployment_environment_name="@ENV@"}'
SPANS = 'resource.service.name="spendwise-api" && resource.deployment.environment.name="@ENV@"'
HTTP_COUNT = "http_server_request_duration_seconds_count"
HTTP_BUCKET = "http_server_request_duration_seconds_bucket"


@dataclass(frozen=True)
class Query:
    id: str
    source: str  # prometheus, loki or tempo
    text: str  # with @ENV@ where the environment goes

    def render(self, environment: str) -> str:
        if not NAME.fullmatch(environment):
            raise ValueError("not an environment name")
        return self.text.replace("@ENV@", environment)


def prom(id: str, expr: str) -> Query:
    return Query(id, "prometheus", expr.replace("@SEL@", SELECTOR))


QUERIES: dict[str, tuple[Query, ...]] = {
    "common": (
        prom("common.version", "count by (service_version) (target_info{@SEL@})"),
        Query("traces.errors", "tempo", "{" + SPANS + " && status=error}"),
    ),
    "http": (
        prom("http.request_rate", f"sum(rate({HTTP_COUNT}{{@SEL@}}[5m]))"),
        prom(
            "http.error_ratio",
            f'sum(rate({HTTP_COUNT}{{@SEL@, http_response_status_code=~"5.."}}[5m]))'
            f" / (sum(rate({HTTP_COUNT}{{@SEL@}}[5m])) > 0)",
        ),
        prom(
            "http.errors_by_route",
            "topk(5, sum by (http_route) "
            f'(rate({HTTP_COUNT}{{@SEL@, http_response_status_code=~"5.."}}[5m])))',
        ),
        prom(
            "http.p95_latency",
            f"histogram_quantile(0.95, sum by (le) (rate({HTTP_BUCKET}{{@SEL@}}[5m])))",
        ),
        prom("http.active_requests", "sum(http_server_active_requests{@SEL@})"),
        Query("logs.http", "loki", LOG_STREAM + ' | detected_level="error"'),
        Query("traces.slow", "tempo", "{" + SPANS + " && duration > 1s}"),
    ),
    "transaction": (
        prom(
            "transaction.saved",
            "sum(increase(spendwise_transaction_created_total{@SEL@}[5m]))",
        ),
        prom(
            "transaction.failed_by_type",
            "sum by (error_type) (increase(spendwise_transaction_create_error_total{@SEL@}[5m]))",
        ),
        prom(
            "transaction.system_failure_ratio",
            "sum(increase(spendwise_transaction_create_error_total"
            '{@SEL@, error_type=~"database|internal"}[5m]))'
            " / ((sum(increase(spendwise_transaction_created_total{@SEL@}[5m]))"
            " + sum(increase(spendwise_transaction_create_error_total{@SEL@}[5m]))) > 0)",
        ),
        Query("logs.transaction", "loki", LOG_STREAM + ' | detected_level="error"'),
    ),
    "ai": (
        prom(
            "ai.requests",
            "sum by (spendwise_ai_provider) "
            "(increase(spendwise_ai_parse_request_total{@SEL@}[5m]))",
        ),
        prom(
            "ai.errors_by_type",
            "sum by (spendwise_ai_provider, error_type) "
            "(increase(spendwise_ai_parse_error_total{@SEL@}[5m]))",
        ),
        prom(
            "ai.failure_ratio",
            "sum(increase(spendwise_ai_parse_error_total{@SEL@}[5m]))"
            " / (sum(increase(spendwise_ai_parse_request_total{@SEL@}[5m])) > 0)",
        ),
        prom(
            "ai.p95_duration",
            "histogram_quantile(0.95, sum by (le) "
            "(rate(spendwise_ai_parse_duration_seconds_bucket{@SEL@}[5m])))",
        ),
        Query("logs.ai", "loki", LOG_STREAM + ' | detected_level="error"'),
    ),
    "auth": (
        prom(
            "auth.refused_per_minute",
            "sum(rate(spendwise_auth_sign_in_failure_total{@SEL@}[5m])) * 60",
        ),
        prom(
            "auth.login_request_rate",
            f'sum(rate({HTTP_COUNT}{{@SEL@, http_route="/api/auth/login"}}[5m]))',
        ),
        Query("logs.auth", "loki", LOG_STREAM + ' |= "Sign-in refused" | detected_level="warn"'),
    ),
}

# Metric labels that may appear in evidence, and what their values may look like.
SAFE_LABELS = frozenset(
    {
        "service_version",
        "http_route",
        "http_response_status_code",
        "error_type",
        "spendwise_ai_provider",
        "spendwise_transaction_type",
        "spendwise_transaction_source",
        "deployment_environment_name",
    }
)
SAFE_VALUE = re.compile(r"[A-Za-z0-9_./:{}-]{1,80}")
LEVELS = ("error", "warn", "info", "debug")
LOGGER = re.compile(r"app(?:\.[a-z0-9_]+)*")
# The warning and error messages the app itself logs (app/api/routes/auth.py, app/core/errors.py).
# Only a line that is exactly one of these is shown to the model; see parse_loki().
LOG_MESSAGES = {
    "sign-in-refused": re.compile(r"Sign-in refused: unknown email or wrong password"),
    "unhandled-error": re.compile(
        r"Unhandled [A-Za-z_][A-Za-z0-9_]{0,60} in [A-Z]{3,7} "
        r"(?:an unmatched route|/[A-Za-z0-9_/{}.-]{0,100})"
    ),
}
SPAN_NAME = re.compile(r"[A-Za-z0-9 /_{}.:-]{1,80}")
TRACE_ID = re.compile(r"[0-9a-f]{32}")


def queries_for(category: str) -> tuple[Query, ...]:
    """The queries run for an incident of this category: the common ones, then its own."""
    return (*QUERIES["common"][:1], *QUERIES[category], *QUERIES["common"][1:])


class BackendError(Exception):
    """A backend didn't give usable evidence. The message is fixed text: no response content."""


class Backends(Protocol):
    def prometheus(self, expr: str) -> object: ...
    def loki(self, expr: str) -> object: ...
    def tempo(self, expr: str) -> object: ...


class HttpBackends:
    """The three backends over HTTP. GET only, fixed hosts, fixed API paths, bounded replies."""

    def __init__(
        self, prometheus: str, loki: str, tempo: str, clock: Callable[[], float] = time.time
    ) -> None:
        self.bases = {
            "prometheus": base(prometheus),
            "loki": base(loki),
            "tempo": base(tempo),
        }
        self.clock = clock

    def prometheus(self, expr: str) -> object:
        return self._get("prometheus", "/api/v1/query", {"query": expr})

    def loki(self, expr: str) -> object:
        now = int(self.clock() * 1e9)
        params = {
            "query": expr,
            "start": now - WINDOW * 10**9,
            "end": now,
            "limit": LOKI_LIMIT,
            "direction": "backward",
        }
        return self._get("loki", "/loki/api/v1/query_range", params)

    def tempo(self, expr: str) -> object:
        now = int(self.clock())
        params = {"q": expr, "limit": MAX_TRACES, "start": now - WINDOW, "end": now}
        return self._get("tempo", "/api/search", params)

    def _get(self, backend: str, path: str, params: dict) -> object:
        host, port = self.bases[backend]
        connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
        try:
            connection.request("GET", f"{path}?{urlencode(params)}")
            response = connection.getresponse()
            if response.status != 200:
                raise BackendError(f"HTTP {response.status}")
            body = response.read(MAX_RESPONSE + 1)
        except (OSError, http.client.HTTPException) as error:
            raise BackendError(f"no answer ({type(error).__name__})") from None
        finally:
            connection.close()
        if len(body) > MAX_RESPONSE:
            raise BackendError("response too large")
        try:
            return json.loads(body)
        except ValueError:
            raise BackendError("malformed response") from None


def base(url: str) -> tuple[str, int]:
    """(host, port) of a plain http://host:port URL; anything else is a configuration error."""
    parts = urlsplit(url)
    if (
        parts.scheme != "http"
        or not parts.hostname
        or not parts.port
        or parts.path not in ("", "/")
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", parts.hostname)
    ):
        raise ValueError("a backend URL must look like http://host:port")
    return parts.hostname, parts.port


# --- What comes back ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One piece of evidence: `data` may be stored in the report, `samples` only go to the model."""

    id: str
    source: str
    query: str
    summary: str
    data: object
    samples: tuple[str, ...] = ()
    problem: str | None = None

    def report(self) -> dict:
        return {
            "id": self.id,
            "basis": "observed",
            "available": self.problem is None,
            "source": self.source,
            "query_id": self.query,
            "summary": self.summary,
            "data": self.data,
        }

    def prompt(self) -> dict:
        return self.report() | ({"log_samples": list(self.samples)} if self.samples else {})

    @property
    def observed(self) -> bool:
        """The query answered and found something. An empty answer is an observation of nothing."""
        return self.problem is None and has_data(self.source, self.data)


@dataclass
class Evidence:
    items: list[Item] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def queries(self) -> list[str]:
        return [item.id for item in self.items]

    @property
    def grounded(self) -> set[str]:
        """What a conclusion may cite: only what a query actually found."""
        return {item.id for item in self.items if item.observed}

    @property
    def silent(self) -> set[str]:
        """Queries that answered and found nothing: absence, which is not evidence."""
        return {item.id for item in self.items if item.problem is None and not item.observed}

    @property
    def sources(self) -> set[str]:
        """Which backends found something."""
        return {item.source for item in self.items if item.observed}


def has_data(source: str, data: object) -> bool:
    """Did a query find anything? Rows for Prometheus and Tempo, lines for Loki."""
    if source == "incident":
        return True
    if source == "loki":
        lines = data.get("lines") if isinstance(data, dict) else None
        return isinstance(lines, int) and not isinstance(lines, bool) and lines > 0
    return isinstance(data, list) and len(data) > 0


def number(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):  # float(10**400) overflows
        return None
    return round(result, 6) if math.isfinite(result) else None


def parse_prometheus(data: object) -> list[dict]:
    """Up to MAX_SERIES {labels, value} rows, largest first; only allowlisted labels survive."""
    payload = (
        data.get("data") if isinstance(data, dict) and data.get("status") == "success" else None
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), list | tuple):
        raise BackendError("unexpected response")
    result = payload["result"]
    if payload.get("resultType") == "scalar":
        result = [{"metric": {}, "value": result}]
    elif payload.get("resultType") != "vector":
        raise BackendError("unexpected response")
    rows = []
    for row in result[:100]:
        try:
            metric, value = row["metric"], number(row["value"][1])
        except (KeyError, IndexError, TypeError):
            raise BackendError("unexpected response") from None
        if value is None or not isinstance(metric, dict):
            continue
        labels = {
            key: val
            for key, val in sorted(metric.items())
            if key in SAFE_LABELS and isinstance(val, str) and SAFE_VALUE.fullmatch(val)
        }
        rows.append({"labels": labels, "value": value})
    rows.sort(key=lambda r: (-r["value"], json.dumps(r["labels"], sort_keys=True)))
    return rows[:MAX_SERIES]


def describe_series(query: str, rows: list[dict]) -> str:
    if not rows:
        return f"{query}: no data in the last 5 minutes"
    shown = []
    for row in rows:
        labels = ", ".join(f"{k}={v}" for k, v in row["labels"].items())
        shown.append(f"{labels}: {row['value']}" if labels else f"{row['value']}")
    return f"{query}: " + "; ".join(shown)


def parse_loki(data: object) -> tuple[dict, tuple[str, ...]]:
    """(counts by level, logger and message kind, up to MAX_SAMPLES recognised lines).

    A log line's text reaches the model only if it is exactly one of the app's own message
    shapes (LOG_MESSAGES). Any other line, whatever it says, is counted as "unrecognised" and
    never shown: free text can't be told from data by its look, so it is kept out by construction.
    """
    payload = (
        data.get("data") if isinstance(data, dict) and data.get("status") == "success" else None
    )
    streams = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(streams, list | tuple):
        raise BackendError("unexpected response")
    levels: dict[str, int] = {}
    loggers: dict[str, int] = {}
    messages: dict[str, int] = {}
    recognised: list[tuple[int, str]] = []
    total = 0
    for stream in streams[:100]:
        labels = stream.get("stream") if isinstance(stream, dict) else None
        values = stream.get("values") if isinstance(stream, dict) else None
        if not isinstance(labels, dict) or not isinstance(values, list):
            raise BackendError("unexpected response")
        level = labels.get("detected_level")
        level = level if level in LEVELS else "other"
        logger = labels.get("scope_name")
        logger = logger if isinstance(logger, str) and LOGGER.fullmatch(logger) else "other"
        for entry in values[: LOKI_LIMIT * 2]:
            try:
                stamp, line = int(entry[0]), entry[1]
            except (IndexError, TypeError, ValueError):
                raise BackendError("unexpected response") from None
            kind = next(
                (
                    k
                    for k, shape in LOG_MESSAGES.items()
                    if isinstance(line, str) and shape.fullmatch(line)
                ),
                "unrecognised",
            )
            total += 1
            levels[level] = levels.get(level, 0) + 1
            loggers[logger] = loggers.get(logger, 0) + 1
            messages[kind] = messages.get(kind, 0) + 1
            if kind != "unrecognised":
                recognised.append((stamp, line))
    recognised.sort(reverse=True)
    counts = {
        "lines": total,
        "levels": dict(sorted(levels.items())),
        "loggers": dict(sorted(loggers.items())),
        "messages": dict(sorted(messages.items())),
    }
    return counts, tuple(line for _, line in recognised[:MAX_SAMPLES])


def describe_logs(query: str, counts: dict) -> str:
    if not counts["lines"]:
        return f"{query}: no matching application log lines in the last 15 minutes"
    levels = ", ".join(f"{k} {v}" for k, v in counts["levels"].items())
    unrecognised = counts["messages"].get("unrecognised", 0)
    text = f"{query}: {counts['lines']} application log lines in the last 15 minutes ({levels})"
    return text + (
        f"; {unrecognised} with a message the responder does not show" if unrecognised else ""
    )


def parse_tempo(data: object) -> list[dict]:
    traces = data.get("traces") if isinstance(data, dict) else None
    if not isinstance(traces, list | tuple):
        raise BackendError("unexpected response")
    found = []
    for trace in traces[:MAX_TRACES]:
        if not isinstance(trace, dict) or not TRACE_ID.fullmatch(str(trace.get("traceID", ""))):
            raise BackendError("unexpected response")
        name = safe_text(trace.get("rootTraceName"), 80)
        started = number(trace.get("startTimeUnixNano"))
        duration = number(trace.get("durationMs", 0))
        found.append(
            {
                "trace_id": trace["traceID"],
                "name": name if name and SPAN_NAME.fullmatch(name) else "[unnamed]",
                "duration_ms": int(min(max(duration or 0, 0), 10**7)),
                "started_at": iso(started / 1e9) if started else None,
            }
        )
    return found


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe_traces(query: str, traces: list[dict]) -> str:
    if not traces:
        return f"{query}: no matching traces in the last 15 minutes"
    return f"{query}: {len(traces)} matching traces in the last 15 minutes"


def run(query: Query, environment: str, backends: Backends, secrets: tuple[str, ...]) -> Item:
    text = query.render(environment)
    item_id = f"{query.source}:{query.id}"
    if query.source == "prometheus":
        rows = parse_prometheus(backends.prometheus(text))
        return Item(item_id, query.source, query.id, describe_series(query.id, rows), rows)
    if query.source == "loki":
        counts, samples = parse_loki(backends.loki(text))
        return Item(
            item_id, query.source, query.id, describe_logs(query.id, counts), counts, samples
        )
    traces = parse_tempo(backends.tempo(text))
    return Item(item_id, query.source, query.id, describe_traces(query.id, traces), traces)


def collect(
    incident: Incident,
    backends: Backends,
    secrets: tuple[str, ...] = (),
    audit: Callable[[str], None] = lambda line: None,
    clock: Callable[[], float] = time.monotonic,
    deadline: float = DEADLINE,
) -> Evidence:
    """Run the incident category's query templates. Failures become limitations, not errors."""
    evidence = Evidence()
    if incident.environment is None:
        evidence.problems.append(
            "The incident names no environment, so no evidence was collected (a query without an "
            "environment would mix environments)."
        )
        return evidence
    end = clock() + deadline
    for query in queries_for(incident.category):
        item_id = f"{query.source}:{query.id}"
        if clock() > end:
            evidence.items.append(
                Item(item_id, query.source, query.id, "skipped", [], problem="deadline")
            )
            evidence.problems.append(f"{item_id} was skipped: the evidence deadline passed.")
            audit(f"evidence: {item_id} skipped (deadline)")
            continue
        try:
            item = run(query, incident.environment, backends, secrets)
            audit(f"evidence: {item_id} ok")
        except BackendError as error:
            item = Item(
                item_id, query.source, query.id, f"{query.id}: unavailable", [], problem=str(error)
            )
            evidence.problems.append(f"{item_id} is unavailable ({error}).")
            audit(f"evidence: {item_id} failed ({error})")
        evidence.items.append(item)
    return evidence
