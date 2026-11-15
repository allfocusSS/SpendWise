"""SpendWise's own metrics: what the application does, as opposed to HTTP (docs/observability.md).

    spendwise.transaction.created        counter    {transaction}  type, source
    spendwise.transaction.create.error   counter    {error}        error.type
    spendwise.auth.sign_in.failure       counter    {attempt}      (none)
    spendwise.ai.parse.request           counter    {request}      provider
    spendwise.ai.parse.error             counter    {error}        provider, error.type
    spendwise.ai.parse.duration          histogram  s              provider (+ error.type if failed)

The instruments are created once, from the process's MeterProvider (get_meter()). Until
telemetry starts, and for good while it is off, they are OpenTelemetry's no-op ones: recording
costs nothing and changes nothing.

Every attribute value comes from a closed set below (an enum of this module, or of the validated
request schema). Never a user ID, email, category name, description, amount, path, exception
message or AI text, so each metric has a handful of series at most.
"""

import enum
import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.metrics import Meter
from sqlalchemy.exc import SQLAlchemyError

from app.ai.provider import AIUnavailableError
from app.core.errors import DomainError
from app.models import TransactionSource, TransactionType
from app.observability.telemetry import get_meter

# The attribute keys (privacy.APPLICATION_METRIC_ATTRIBUTES). A view (telemetry.py) drops any
# other key, whatever code passes.
TRANSACTION_TYPE = "spendwise.transaction.type"
TRANSACTION_SOURCE = "spendwise.transaction.source"
AI_PROVIDER = "spendwise.ai.provider"
ERROR_TYPE = "error.type"

# Seconds. From an in-process provider (milliseconds) to a slow model call (tens of seconds).
AI_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


class ErrorType(enum.StrEnum):
    """Why an operation failed. Never derived from exception names or messages."""

    VALIDATION = "validation"  # the request broke a business rule (e.g. an unknown category)
    PROVIDER = "provider"  # the AI provider was unavailable or failed
    DATABASE = "database"  # the database refused or was unreachable
    INTERNAL = "internal"  # anything else: a bug


class AIProviderName(enum.StrEnum):
    FAKE = "fake"
    ANTHROPIC = "anthropic"
    OTHER = "other"  # a provider this list doesn't know yet, never its own name


def classify(exc: BaseException) -> ErrorType:
    if isinstance(exc, AIUnavailableError):
        return ErrorType.PROVIDER
    if isinstance(exc, DomainError):
        return ErrorType.VALIDATION
    if isinstance(exc, SQLAlchemyError):
        return ErrorType.DATABASE
    return ErrorType.INTERNAL


def provider_label(name: str) -> AIProviderName:
    try:
        return AIProviderName(name)
    except ValueError:
        return AIProviderName.OTHER


class _Instruments:
    def __init__(self, meter: Meter) -> None:
        self.transaction_created = meter.create_counter(
            "spendwise.transaction.created",
            unit="{transaction}",
            description="Transactions saved.",
        )
        self.transaction_create_error = meter.create_counter(
            "spendwise.transaction.create.error",
            unit="{error}",
            description="Attempts to save a transaction that failed, by error type.",
        )
        self.sign_in_failure = meter.create_counter(
            "spendwise.auth.sign_in.failure",
            unit="{attempt}",
            description="Sign-ins refused (unknown email or wrong password, never which).",
        )
        self.ai_parse_request = meter.create_counter(
            "spendwise.ai.parse.request",
            unit="{request}",
            description="Requests to the AI provider to turn text into a transaction draft.",
        )
        self.ai_parse_error = meter.create_counter(
            "spendwise.ai.parse.error",
            unit="{error}",
            description="AI transaction parsing requests that failed, by error type.",
        )
        self.ai_parse_duration = meter.create_histogram(
            "spendwise.ai.parse.duration",
            unit="s",
            description="Time the AI provider took to parse a transaction, success or failure.",
            explicit_bucket_boundaries_advisory=AI_DURATION_BUCKETS,
        )


_instruments = _Instruments(get_meter(__name__))


def bind(meter: Meter) -> None:
    """Record into this meter from now on (tests, with their own in-memory MeterProvider)."""
    global _instruments
    _instruments = _Instruments(meter)


def initialize(ai_provider: str) -> None:
    """Start every counter series at zero (when telemetry starts, after the MeterProvider is set).

    A counter otherwise appears in Prometheus only with its first value already counted, and
    increase()/rate() can't see that first change: the first transactions, failures or refused
    sign-ins after a restart would never show. Every combination is known in advance (the
    attributes are closed sets), so this adds a handful of series, never more.
    """
    for type_ in TransactionType:
        for source in TransactionSource:
            _instruments.transaction_created.add(
                0, {TRANSACTION_TYPE: type_.value, TRANSACTION_SOURCE: source.value}
            )
    for error in (ErrorType.VALIDATION, ErrorType.DATABASE, ErrorType.INTERNAL):
        _instruments.transaction_create_error.add(0, {ERROR_TYPE: error.value})
    _instruments.sign_in_failure.add(0)
    provider = {AI_PROVIDER: provider_label(ai_provider).value}
    _instruments.ai_parse_request.add(0, provider)
    for error in (ErrorType.PROVIDER, ErrorType.VALIDATION):
        _instruments.ai_parse_error.add(0, {**provider, ERROR_TYPE: error.value})


@contextmanager
def creating_transaction(type_: TransactionType, source: TransactionSource) -> Iterator[None]:
    """Counts the block once: as created if it completes, else as one error, by its type."""
    try:
        yield
    except Exception as exc:
        _instruments.transaction_create_error.add(1, {ERROR_TYPE: classify(exc).value})
        raise
    _instruments.transaction_created.add(
        1,
        {
            TRANSACTION_TYPE: TransactionType(type_).value,
            TRANSACTION_SOURCE: TransactionSource(source).value,
        },
    )


def sign_in_failed() -> None:
    _instruments.sign_in_failure.add(1)


@contextmanager
def parsing_with_ai(provider: str) -> Iterator[None]:
    """Counts one parse request, its duration (monotonic clock) and, if it fails, one error.

    A failure inside the provider is a provider error, unless the provider rejected the input
    with a domain error (validation).
    """
    attributes = {AI_PROVIDER: provider_label(provider).value}
    _instruments.ai_parse_request.add(1, attributes)
    started = time.monotonic()
    try:
        yield
    except Exception as exc:
        error = (
            ErrorType.VALIDATION
            if isinstance(exc, DomainError) and not isinstance(exc, AIUnavailableError)
            else ErrorType.PROVIDER
        )
        failed = {**attributes, ERROR_TYPE: error.value}
        _instruments.ai_parse_error.add(1, failed)
        _instruments.ai_parse_duration.record(time.monotonic() - started, failed)
        raise
    _instruments.ai_parse_duration.record(time.monotonic() - started, attributes)
