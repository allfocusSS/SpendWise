"""Observability for the SpendWise API: OpenTelemetry traces, metrics and logs.

See docs/observability.md.

For code that adds its own telemetry:

    from app.observability import get_meter, get_tracer

    tracer = get_tracer(__name__)
    with tracer.start_as_current_span("categorize"):
        ...

Both work whether telemetry is on or off, so no caller needs to check. Logs need nothing new:
logging.getLogger(__name__) under app/ is exported with the request's trace context.
"""

from app.observability.logs import APP_LOGGER, configure_logging
from app.observability.telemetry import (
    Telemetry,
    build_resource,
    build_telemetry,
    get_meter,
    get_tracer,
    instrument_app,
    setup_telemetry,
    shutdown_telemetry,
)

__all__ = [
    "APP_LOGGER",
    "Telemetry",
    "build_resource",
    "build_telemetry",
    "configure_logging",
    "get_meter",
    "get_tracer",
    "instrument_app",
    "setup_telemetry",
    "shutdown_telemetry",
]
