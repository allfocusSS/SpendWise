"""What SpendWise telemetry must never contain (docs/observability.md, "Data policy").

Telemetry describes the service, not the people using it. The HTTP instrumentation records no
bodies and, unless asked to, no headers. These rules hold even if someone asks it to (the
OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_* variables) or a newer version records more:

- spans lose every header attribute, the client's address and browser, and query strings,
  before they leave the process (RedactingSpanProcessor);
- exceptions recorded on spans keep their type only: no message, no stack trace, no status
  description;
- HTTP metrics keep only a fixed set of bounded attributes (HTTP_METRIC_ATTRIBUTES), and so do
  SpendWise's own metrics (APPLICATION_METRIC_ATTRIBUTES).
"""

from opentelemetry.context import Context
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import Status, StatusCode

# Attributes of server spans that describe the person rather than the request: their IP address
# and port, their browser, and the query string (free to carry anything a future endpoint
# accepts). Current semantic conventions first, then the older names the same instrumentation
# uses when OTEL_SEMCONV_STABILITY_OPT_IN asks for them.
DROPPED_SPAN_ATTRIBUTES = frozenset(
    {
        "client.address",
        "client.port",
        "user_agent.original",
        "url.query",
        "url.full",
        "http.client_ip",
        "http.url",
        "http.user_agent",
        "net.peer.ip",
        "net.peer.port",
        "net.sock.peer.addr",
        "net.sock.peer.port",
    }
)
# Captured request and response headers (Authorization, Cookie, Set-Cookie, ...): never exported.
DROPPED_SPAN_ATTRIBUTE_PREFIXES = ("http.request.header.", "http.response.header.")

# What an exception event keeps. Its message and stack trace can quote user data: PostgreSQL's
# DETAIL line names the values that broke a constraint (creating the same category twice at once
# shows its name), and hide_parameters doesn't cover what the database server says. The
# span keeps its ERROR status and error.type, the request's log record says which exception it
# was, and the full traceback stays in the server's own log, which isn't exported.
EXCEPTION_EVENT_ATTRIBUTES = frozenset({"exception.type", "exception.escaped"})

# The only attributes HTTP server metrics may have. All bounded: the route template (never the
# path itself), the method (unknown ones become _OTHER), the status code and the error type.
HTTP_METRIC_ATTRIBUTES = frozenset(
    {
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "error.type",
        "url.scheme",
        "network.protocol.name",
        "network.protocol.version",
    }
)


# The only attributes SpendWise's own metrics (spendwise.*, metrics.py) may have. Each value comes
# from a closed set: the transaction type and source of the validated request, the AI provider's
# name from a fixed list, and metrics.ErrorType.
APPLICATION_METRIC_ATTRIBUTES = frozenset(
    {
        "spendwise.transaction.type",
        "spendwise.transaction.source",
        "spendwise.ai.provider",
        "error.type",
    }
)


def is_dropped(key: str) -> bool:
    return key in DROPPED_SPAN_ATTRIBUTES or key.startswith(DROPPED_SPAN_ATTRIBUTE_PREFIXES)


def _redact_event(event: Event) -> Event:
    if event.name != "exception":
        return event
    attributes = {
        key: value
        for key, value in (event.attributes or {}).items()
        if key in EXCEPTION_EVENT_ATTRIBUTES
    }
    return Event(event.name, attributes, event.timestamp)


def redact(span: ReadableSpan) -> ReadableSpan:
    """The span without what must not leave the process (the same object if it has none)."""
    attributes = span.attributes or {}
    events = tuple(_redact_event(event) for event in span.events)
    # The SDK describes an exception's status as "Type: message" (e.g. for spans of
    # get_tracer()); the code alone says it failed.
    status = span.status
    if status.status_code is StatusCode.ERROR and status.description:
        status = Status(StatusCode.ERROR)
    if (
        not any(is_dropped(key) for key in attributes)
        and all(new is old for new, old in zip(events, span.events, strict=True))
        and status is span.status
    ):
        return span
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes={k: v for k, v in attributes.items() if not is_dropped(k)},
        events=events,
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanProcessor(SpanProcessor):
    """Hands finished spans, redacted, to the processor that exports them."""

    def __init__(self, exporting: SpanProcessor) -> None:
        self._exporting = exporting

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._exporting.on_start(span, parent_context=parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._exporting.on_end(redact(span))

    def shutdown(self) -> None:
        self._exporting.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._exporting.force_flush(timeout_millis)
