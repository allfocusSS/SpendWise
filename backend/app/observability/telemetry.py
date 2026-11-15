"""The OpenTelemetry SDK for the SpendWise API: one resource, three providers (traces, metrics,
logs), OTLP/HTTP exporters to the Collector, the logging bridge and the FastAPI instrumentation.

See docs/observability.md. Nothing here runs unless OTEL_ENABLED=true: with telemetry off,
setup_telemetry() returns None without importing exporters, starting threads or touching the
network, and get_tracer()/get_meter() hand out OpenTelemetry's no-op implementations.
"""

import atexit
import logging
import os
import threading
from collections.abc import Sequence

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, Sampler, TraceIdRatioBased

from app.core.config import Settings
from app.observability.logs import APP_LOGGER
from app.observability.privacy import HTTP_METRIC_ATTRIBUTES, RedactingSpanProcessor

log = logging.getLogger(__name__)

# Each OTLP request, retries included, gives up after this long: a missing Collector costs a few
# background seconds, never a user request, and keeps shutdown bounded.
EXPORT_TIMEOUT = 5.0
SHUTDOWN_TIMEOUT_MILLIS = 5000
# Probes polled all day by Docker, Render, the deploy gateway and the promotion workflow: no
# spans and no HTTP metrics for them. Matched against scheme://host/path (no query string), and
# only these exact paths.
EXCLUDED_PATHS = ("/api/health", "/api/health/ready", "/api/meta")
EXCLUDED_URLS = ",".join(rf"^https?://[^/]*{path}$" for path in EXCLUDED_PATHS)


def build_resource(settings: Settings) -> Resource:
    """The resource of every span, metric and log: Settings.resource_attributes().

    OTEL_RESOURCE_ATTRIBUTES can add attributes, never replace these.
    """
    return Resource.create(settings.resource_attributes())


def build_sampler(ratio: float) -> Sampler:
    """Parent-based, trace-ID ratio sampling.

    Spans inside a sampled request are kept with it. Requests decide by ratio, also when the
    client sends a traceparent header: an outside caller can't make SpendWise keep (or drop)
    its traces.
    """
    by_ratio = TraceIdRatioBased(ratio)
    return ParentBased(
        root=by_ratio, remote_parent_sampled=by_ratio, remote_parent_not_sampled=by_ratio
    )


class Telemetry:
    """The SDK of one process: three providers sharing one resource, and the logging handler."""

    def __init__(
        self,
        resource: Resource,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
        logger_provider: LoggerProvider,
    ) -> None:
        # Imported here: the handler module sets up a logger of its own on import.
        from opentelemetry.instrumentation.logging.handler import LoggingHandler

        self.resource = resource
        self.tracer_provider = tracer_provider
        self.meter_provider = meter_provider
        self.logger_provider = logger_provider
        # INFO and up, like the console. Each record keeps the trace context it was logged in.
        self.log_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
        self._lock = threading.Lock()
        self._shut_down = False

    def force_flush(self, timeout_millis: int = SHUTDOWN_TIMEOUT_MILLIS) -> bool:
        """Export everything buffered now (tests, and before a planned stop)."""
        return all(
            [
                self.tracer_provider.force_flush(timeout_millis),
                self.logger_provider.force_flush(timeout_millis),
                self.meter_provider.force_flush(timeout_millis),
            ]
        )

    def shutdown(self) -> None:
        """Flush and stop every exporter; once (later calls do nothing). Bounded in time."""
        with self._lock:
            if self._shut_down:
                return
            self._shut_down = True
        # No log record may arrive at a pipeline that is shutting down.
        logging.getLogger(APP_LOGGER).removeHandler(self.log_handler)
        self.tracer_provider.shutdown()
        self.logger_provider.shutdown()
        self.meter_provider.shutdown(timeout_millis=SHUTDOWN_TIMEOUT_MILLIS)


def build_telemetry(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_readers: Sequence[MetricReader] | None = None,
    log_exporter: LogRecordExporter | None = None,
) -> Telemetry:
    """The providers for these settings. Sets no globals, so tests can build as many as needed.

    By default everything goes to OTEL_EXPORTER_OTLP_ENDPOINT over OTLP/HTTP (protobuf). Tests
    pass in-memory exporters instead. Batching and the metric export interval follow the
    standard variables (OTEL_BSP_*, OTEL_BLRP_*, OTEL_METRIC_EXPORT_INTERVAL; the SDK defaults
    are 5 s for spans, 1 s for logs and 60 s for metrics).
    """
    resource = build_resource(settings)
    endpoint = settings.otel_exporter_otlp_endpoint
    if endpoint is None and None in (span_exporter, metric_readers, log_exporter):
        raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT is not set")

    if span_exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        span_exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=EXPORT_TIMEOUT)
    if metric_readers is None:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        metric_readers = [
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=EXPORT_TIMEOUT)
            )
        ]
    if log_exporter is None:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

        log_exporter = OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", timeout=EXPORT_TIMEOUT)

    # shutdown_on_exit=False: Telemetry.shutdown() is the one shutdown (lifespan, else atexit).
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=build_sampler(settings.traces_sample_ratio),
        shutdown_on_exit=False,
    )
    tracer_provider.add_span_processor(RedactingSpanProcessor(BatchSpanProcessor(span_exporter)))

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=list(metric_readers),
        # HTTP server metrics keep only bounded attributes, whatever the instrumentation adds.
        views=[View(instrument_name="http.server.*", attribute_keys=set(HTTP_METRIC_ATTRIBUTES))],
        shutdown_on_exit=False,
    )

    logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

    return Telemetry(resource, tracer_provider, meter_provider, logger_provider)


# --- This process -------------------------------------------------------------------------

_lock = threading.Lock()
_telemetry: Telemetry | None = None


def setup_telemetry(settings: Settings) -> Telemetry | None:
    """Start telemetry for this process, once; None when it is off.

    The first call builds the providers, makes them OpenTelemetry's global providers (what
    get_tracer() and get_meter() use) and connects the "app" loggers. Later calls, e.g. from
    another create_app(), return the same Telemetry: global providers can only be set once, and
    a second set of handlers would export every log record twice.
    """
    global _telemetry
    if not settings.telemetry_enabled:
        return None
    with _lock:
        if _telemetry is None:
            telemetry = build_telemetry(settings)
            trace.set_tracer_provider(telemetry.tracer_provider)
            metrics.set_meter_provider(telemetry.meter_provider)
            logging.getLogger(APP_LOGGER).addHandler(telemetry.log_handler)
            atexit.register(telemetry.shutdown)  # if the app never ran its lifespan shutdown
            _telemetry = telemetry
            log.info(
                "Telemetry on: OTLP/HTTP to %s, %.0f%% of traces",
                settings.otel_exporter_otlp_endpoint,
                settings.traces_sample_ratio * 100,
            )
        return _telemetry


def shutdown_telemetry() -> None:
    """Flush and stop this process's telemetry (the app's lifespan calls it). Safe when off."""
    with _lock:
        telemetry = _telemetry
    if telemetry is not None:
        telemetry.shutdown()


def instrument_app(app: FastAPI, telemetry: Telemetry) -> None:
    """Server spans and HTTP metrics for every request, except the probes (EXCLUDED_PATHS).

    No request or response bodies, no headers (privacy.py drops them even if the
    OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_* variables ask for them), and no ASGI
    receive/send child spans. Spans are named after the route template, e.g.
    "GET /api/transactions/{transaction_id}".
    """
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    # Current HTTP semantic conventions: http.route, http.request.method, http.response.status_code
    # and http.server.request.duration (seconds). The older ones put the client's Host header on
    # every metric. Read once per process, when the first app is instrumented.
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "http"
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        excluded_urls=EXCLUDED_URLS,
        exclude_spans=["receive", "send"],
    )


def get_tracer(name: str) -> trace.Tracer:
    """A tracer for code that adds its own spans; a no-op one while telemetry is off."""
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """A meter for application metrics; a no-op one while telemetry is off.

    Attribute values must be bounded (an enum, a status), never user input, IDs or amounts.
    """
    return metrics.get_meter(name)
