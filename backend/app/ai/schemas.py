"""Typed inputs and outputs for AI providers.

Rule: provider OUTPUTS never contain money as numbers. A transaction draft carries the amount
exactly as the user wrote it (`amount_text`); the backend converts it to tiyn. For insights a
provider only selects topics (typed enum) and may add advice text without figures; the backend
chooses and renders every sentence that states a figure (see app/ai/facts.py).
"""

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import TransactionType
from app.schemas.common import TIYN_DESCRIPTION, MoneyCents

MAX_PROMPT_CHARS = 500

PromptText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PROMPT_CHARS)
]

# ---------------------------------------------------------------------------
# Natural-language transaction entry
# ---------------------------------------------------------------------------


class CategoryOption(BaseModel):
    """A category the provider may choose from (it must not invent new ones)."""

    id: int
    name: str
    type: TransactionType


class TransactionDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: PromptText
    categories: list[CategoryOption]
    # Passed in (not read from the clock) so "today"/"yesterday" are deterministic and testable.
    today: date


class TransactionDraft(BaseModel):
    """An unsaved suggestion. The user must review it before anything is stored."""

    amount_text: str | None = Field(
        description=(
            "The amount exactly as written in the user's text (e.g. '2 500,50'), or null if "
            "none was found. The backend converts it to tiyn; the AI never produces numbers."
        )
    )
    type: TransactionType
    category_id: int | None = Field(description="One of the offered category ids, or null.")
    description: str = Field(max_length=255)
    occurred_on: date
    notes: list[str] = Field(
        default_factory=list, description="What the provider guessed or could not determine."
    )


# ---------------------------------------------------------------------------
# Spending insights
# ---------------------------------------------------------------------------

# Income, expense and category totals are sums of positive amounts: never negative.
NonNegativeMoneyCents = Annotated[int, Field(ge=0, description=TIYN_DESCRIPTION)]

# Change vs the previous period: cannot fall below -100%; capped so absurd values (e.g. growth from
# almost nothing) are rejected instead of rendered as enormous numbers.
MAX_CHANGE_PERCENTAGE = 1_000_000


class CategoryShare(BaseModel):
    """One category's backend-calculated total and share of the period."""

    name: str = Field(max_length=50)
    total_cents: NonNegativeMoneyCents
    percentage: float = Field(
        ge=0, le=100, allow_inf_nan=False, description="Backend-calculated share, 0–100."
    )


class SpendingSummary(BaseModel):
    """Figures calculated by the backend analytics service. The AI only interprets them."""

    period_label: str = Field(description="Human-readable period, e.g. 'October 2026'.")
    total_income_cents: NonNegativeMoneyCents
    total_expense_cents: NonNegativeMoneyCents
    balance_cents: MoneyCents  # may be negative
    transaction_count: int = Field(ge=0)
    top_expense_categories: list[CategoryShare] = Field(default_factory=list)
    expense_change_percentage: float | None = Field(
        default=None,
        ge=-100,
        le=MAX_CHANGE_PERCENTAGE,
        allow_inf_nan=False,
        description="Backend-calculated change in expenses vs the previous period, in percent "
        "(negative = decrease).",
    )


class InsightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: SpendingSummary


class InsightTopic(StrEnum):
    """What a provider may ask to be explained. The backend picks the exact sentence."""

    OVERVIEW = "overview"
    BALANCE = "balance"
    TOP_CATEGORY = "top_category"
    EXPENSE_CHANGE = "expense_change"


class InsightSelection(BaseModel):
    """Provider output for one insight: a topic plus optional advice without figures."""

    model_config = ConfigDict(extra="forbid")

    topic: InsightTopic
    advice: str | None = Field(default=None, max_length=300)


class InsightsResult(BaseModel):
    provider: str
    insights: list[InsightSelection]


class SentenceId(StrEnum):
    """Backend sentence templates. Chosen by the backend from the actual sign of each figure."""

    NO_ACTIVITY = "no_activity"
    OVERVIEW = "overview"
    BALANCE_SURPLUS = "balance_surplus"
    BALANCE_DEFICIT = "balance_deficit"
    BALANCE_EVEN = "balance_even"
    TOP_CATEGORY = "top_category"
    EXPENSE_INCREASE = "expense_increase"
    EXPENSE_DECREASE = "expense_decrease"
    EXPENSE_UNCHANGED = "expense_unchanged"


class Insight(BaseModel):
    """What users see: a backend-rendered sentence plus the provider's validated advice."""

    sentence_id: SentenceId
    title: str
    message: str
    advice: str | None = None
