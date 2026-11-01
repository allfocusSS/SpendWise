"""The AI layer never calculates, changes or invents money amounts."""

import pytest

from app.ai import FakeAIProvider
from app.ai.facts import find_ungrounded_numbers, summary_facts
from app.ai.schemas import (
    CategoryOption,
    CategoryShare,
    InsightsRequest,
    InsightsResult,
    SpendingSummary,
    TransactionDraft,
    TransactionDraftRequest,
)
from app.core.money import format_kzt


def numeric_properties(schema: dict, defs: dict | None = None, path: str = "") -> set[str]:
    """Every integer/number property in a JSON schema, following $refs."""
    defs = defs if defs is not None else schema.get("$defs", {})
    found = set()
    for name, prop in schema.get("properties", {}).items():
        options = prop.get("anyOf", [prop])
        for option in options:
            if "$ref" in option:
                ref = defs[option["$ref"].split("/")[-1]]
                found |= numeric_properties(ref, defs, f"{path}{name}.")
            elif option.get("type") == "array" and "$ref" in option.get("items", {}):
                ref = defs[option["items"]["$ref"].split("/")[-1]]
                found |= numeric_properties(ref, defs, f"{path}{name}[].")
            elif option.get("type") in ("integer", "number"):
                found.add(f"{path}{name}")
    return found


@pytest.mark.parametrize(
    "model,allowed",
    [
        (TransactionDraft, {"category_id"}),  # an id chosen from the offered list, not money
        (InsightsResult, set()),
    ],
)
def test_provider_outputs_have_no_numeric_money_fields(model, allowed: set[str]) -> None:
    assert numeric_properties(model.model_json_schema()) == allowed


SUMMARIES = [
    SpendingSummary(
        period_label="October 2026",
        total_income_cents=500_000_50,
        total_expense_cents=150_000_00,
        balance_cents=350_000_50,
        transaction_count=5,
        top_expense_categories=[
            CategoryShare(name="Groceries", total_cents=1_00, percentage=66.67)
        ],
        expense_change_percentage=12.5,
    ),
    SpendingSummary(
        period_label="Q3 2026",
        total_income_cents=1,
        total_expense_cents=999_999_999_999,
        balance_cents=-999_999_999_998,
        transaction_count=1234,
        top_expense_categories=[
            CategoryShare(name="Housing", total_cents=900_000_000_000, percentage=90.0),
            CategoryShare(name="Food", total_cents=99_999_999_999, percentage=10.0),
        ],
        expense_change_percentage=-33.33,
    ),
    SpendingSummary(
        period_label="All time",
        total_income_cents=0,
        total_expense_cents=0,
        balance_cents=0,
        transaction_count=0,
    ),
]


@pytest.mark.parametrize("summary", SUMMARIES, ids=lambda s: s.period_label)
def test_every_number_in_insights_comes_from_backend_facts(summary: SpendingSummary) -> None:
    result = FakeAIProvider().generate_insights(InsightsRequest(summary=summary))
    text = " ".join(f"{i.title} {i.message}" for i in result.insights)

    assert find_ungrounded_numbers(text, summary_facts(summary)) == set()


def test_balance_is_quoted_not_recalculated() -> None:
    # Deliberately inconsistent figures: income − expenses would be 300 000 ₸, but the backend
    # says 123 456,78 ₸. The provider must repeat the backend's figure and never "fix" it.
    summary = SpendingSummary(
        period_label="October 2026",
        total_income_cents=500_000_00,
        total_expense_cents=200_000_00,
        balance_cents=123_456_78,
        transaction_count=3,
    )

    text = " ".join(
        i.message
        for i in FakeAIProvider().generate_insights(InsightsRequest(summary=summary)).insights
    )

    assert format_kzt(123_456_78) in text
    assert format_kzt(300_000_00) not in text


@pytest.mark.parametrize(
    "text",
    [
        "taxi 2500",
        "Magnum 12 345,50 ₸",
        "salary 450 000 tenge",
        "2 coffees 1500 tenge",
        "cafe 19.99",
    ],
)
def test_draft_amount_is_verbatim_user_text(text: str) -> None:
    request = TransactionDraftRequest(
        text=text,
        categories=[CategoryOption(id=1, name="Other expenses", type="expense")],
        today="2026-11-01",
    )

    result = FakeAIProvider().parse_transaction(request)

    assert isinstance(result.amount_text, str)
    assert result.amount_text in text  # copied from the input, never computed
