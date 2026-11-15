"""Python logging for SpendWise: the standard logging API, application loggers under "app".

configure_logging() gives the "app" loggers a console handler (INFO and up, with the request's
trace and span IDs when there is one). With telemetry on, setup_telemetry() adds the
OpenTelemetry handler to the same logger, so those records also go out over OTLP, each with the
trace context it was logged in.

Only "app" loggers are exported. Not Uvicorn's access log (client addresses and full URLs, and
the spans already describe every request), not SQLAlchemy, and not OpenTelemetry's own loggers,
which therefore can never feed their own export errors back into the export.
"""

import logging

from opentelemetry import trace

APP_LOGGER = "app"
_CONSOLE_HANDLER = "spendwise-console"


class _ConsoleFormatter(logging.Formatter):
    """Appends " trace_id=… span_id=…" to lines logged inside a span.

    Computed while formatting: the record itself is shared with the OpenTelemetry handler, and
    every attribute added to it would be exported.
    """

    def formatMessage(self, record: logging.LogRecord) -> str:
        # Uvicorn's layout: "INFO:     ", "WARNING:  ", then the logger and the message.
        line = f"{record.levelname + ':':<10}{record.name}: {record.message}"
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            line += f" trace_id={context.trace_id:032x} span_id={context.span_id:016x}"
        return line


def configure_logging() -> logging.Logger:
    """The "app" logger at INFO with one console handler; safe to call again (no duplicates)."""
    logger = logging.getLogger(APP_LOGGER)
    if not any(handler.get_name() == _CONSOLE_HANDLER for handler in logger.handlers):
        handler = logging.StreamHandler()  # stderr, like Uvicorn's own log
        handler.set_name(_CONSOLE_HANDLER)
        handler.setFormatter(_ConsoleFormatter())
        logger.addHandler(handler)
    if logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    return logger
