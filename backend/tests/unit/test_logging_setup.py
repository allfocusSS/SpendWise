"""Console logging for the "app" loggers (app/observability/logs.py)."""

import io
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider

from app.observability.logs import APP_LOGGER, configure_logging


@pytest.fixture
def console() -> io.StringIO:
    configure_logging()
    (handler,) = [
        h for h in logging.getLogger(APP_LOGGER).handlers if h.get_name() == "spendwise-console"
    ]
    stream = io.StringIO()
    previous = handler.setStream(stream)
    yield stream
    handler.setStream(previous)


def test_configuring_again_adds_no_second_handler() -> None:
    for _ in range(3):
        logger = configure_logging()
    consoles = [h for h in logger.handlers if h.get_name() == "spendwise-console"]
    assert len(consoles) == 1
    assert logger.level == logging.INFO


def test_console_lines_look_like_uvicorns(console) -> None:
    logging.getLogger("app.example").warning("Something happened")
    assert console.getvalue() == "WARNING:  app.example: Something happened\n"


def test_debug_is_not_shown(console) -> None:
    logging.getLogger("app.example").debug("noise")
    assert console.getvalue() == ""


def test_lines_logged_in_a_span_carry_its_ids(console) -> None:
    tracer = TracerProvider().get_tracer("tests")
    with tracer.start_as_current_span("request") as span:
        logging.getLogger("app.example").info("inside")
    context = span.get_span_context()
    assert console.getvalue() == (
        f"INFO:     app.example: inside trace_id={context.trace_id:032x} "
        f"span_id={context.span_id:016x}\n"
    )


def test_the_console_adds_nothing_to_the_record() -> None:
    # The record is shared with the OpenTelemetry handler, which exports its extra attributes.
    configure_logging()
    seen: list[logging.LogRecord] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    keep = Keep()
    logger = logging.getLogger(APP_LOGGER)
    logger.addHandler(keep)
    try:
        before = set(vars(logging.makeLogRecord({})))
        logging.getLogger("app.example").info("hello %s", "there")
    finally:
        logger.removeHandler(keep)
    (record,) = seen
    assert set(vars(record)) - before <= {"message"}  # set by any formatter; not exported
