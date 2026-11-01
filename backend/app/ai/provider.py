"""The interface every AI provider implements, and the errors providers may raise."""

from typing import Protocol, runtime_checkable

from app.ai.schemas import (
    InsightsRequest,
    InsightsResult,
    TransactionDraft,
    TransactionDraftRequest,
)
from app.core.errors import DomainError


@runtime_checkable
class AIProvider(Protocol):
    """What SpendWise needs from an AI backend.

    Implementations: FakeAIProvider (deterministic, offline) and, in Issue #2, an Anthropic
    provider. Providers interpret text and backend-calculated figures; they never calculate,
    change or invent money amounts.
    """

    name: str

    def parse_transaction(self, request: TransactionDraftRequest) -> TransactionDraft:
        """Turn free text like "taxi 2500 yesterday" into an unsaved draft."""
        ...

    def generate_insights(self, request: InsightsRequest) -> InsightsResult:
        """Explain a backend-calculated spending summary in plain language."""
        ...


class AIUnavailableError(DomainError):
    """AI cannot be used right now (not configured, missing credentials, provider down).

    The message is shown to users, so it must never contain secrets.
    """

    status_code = 503
