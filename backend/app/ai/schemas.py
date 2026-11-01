"""Typed inputs and outputs for AI providers.

Rule: provider OUTPUTS never contain money as numbers. A transaction draft carries the amount
exactly as the user wrote it (`amount_text`); the backend converts it to tiyn. Insights are text
that may only quote figures the backend calculated (see app/ai/facts.py).
"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import TransactionType
from app.schemas.common import MoneyCents

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


class CategoryShare(BaseModel):
    """One category's backend-calculated total and share of the period."""

    name: str
    total_cents: MoneyCents
    percentage: float = Field(description="Backend-calculated share, 0–100.")


class SpendingSummary(BaseModel):
    """Figures calculated by the backend analytics service. The AI only interprets them."""

    period_label: str = Field(description="Human-readable period, e.g. 'October 2026'.")
    total_income_cents: MoneyCents
    total_expense_cents: MoneyCents
    balance_cents: MoneyCents
    transaction_count: int = Field(ge=0)
    top_expense_categories: list[CategoryShare] = Field(default_factory=list)
    expense_change_percentage: float | None = Field(
        default=None,
        description="Backend-calculated change in expenses vs the previous period, in percent.",
    )


class InsightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: SpendingSummary


class Insight(BaseModel):
    title: str
    message: str


class InsightsResult(BaseModel):
    provider: str
    insights: list[Insight]
