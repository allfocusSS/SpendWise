"""An AI provider with metrics: every parse request, its duration and its failures.

build_ai_provider() wraps each provider in this, so whatever calls the provider is measured once,
at the provider call itself (spendwise.ai.parse.*, app/observability/metrics.py). Nothing about
the request or the draft (text, categories, amounts) reaches the metrics: only the provider's
name from a fixed list and a bounded error type.
"""

from app.ai.provider import AIProvider
from app.ai.schemas import (
    InsightsRequest,
    InsightsResult,
    TransactionDraft,
    TransactionDraftRequest,
)
from app.observability import metrics as app_metrics


class MeteredAIProvider:
    def __init__(self, provider: AIProvider) -> None:
        self._provider = provider
        self.name = provider.name

    @property
    def wrapped(self) -> AIProvider:
        """The provider itself."""
        return self._provider

    def parse_transaction(self, request: TransactionDraftRequest) -> TransactionDraft:
        with app_metrics.parsing_with_ai(self.name):
            return self._provider.parse_transaction(request)

    def generate_insights(self, request: InsightsRequest) -> InsightsResult:
        return self._provider.generate_insights(request)
