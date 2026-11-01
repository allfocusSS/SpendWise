"""The AI layer never calculates, changes or invents money amounts."""

from typing import Annotated, Literal, Union

import pytest
from pydantic import BaseModel, Field

from app.ai import FakeAIProvider
from app.ai.facts import render_insights
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

# ---------------------------------------------------------------------------
# Schema inspection: find every integer/number anywhere in a JSON schema
# ---------------------------------------------------------------------------

NUMERIC_TYPES = {"integer", "number"}


def numeric_paths(schema: dict) -> set[str]:
    """Paths of every integer/number value a schema allows, however deeply it is nested.

    Follows $ref/$defs, properties, list items (incl. prefixItems), dict values
    (additionalProperties/patternProperties) and anyOf/oneOf/allOf (Optional, Union, …).
    """
    defs = schema.get("$defs", {})
    found: set[str] = set()

    def walk(node: object, path: str, seen_refs: frozenset[str]) -> None:
        if not isinstance(node, dict):
            return
        if ref := node.get("$ref"):
            name = ref.split("/")[-1]
            if name not in seen_refs:  # guard against recursive models
                walk(defs[name], path, seen_refs | {name})
        types = node.get("type")
        if (set(types) if isinstance(types, list) else {types}) & NUMERIC_TYPES:
            found.add(path or "<root>")
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            for option in node.get(key, []):
                walk(option, path, seen_refs)
        for name, prop in node.get("properties", {}).items():
            walk(prop, f"{path}.{name}" if path else name, seen_refs)
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{path}[]", seen_refs)
        if isinstance(node.get("additionalProperties"), dict):
            walk(node["additionalProperties"], f"{path}{{}}", seen_refs)
        for pattern_prop in node.get("patternProperties", {}).values():
            walk(pattern_prop, f"{path}{{}}", seen_refs)

    walk(schema, "", frozenset())
    return found


class TestNumericPathsDetector:
    """Self-tests: the detector must not miss money hidden in containers or unions."""

    def test_detects_lists_dicts_nested_optional_and_union(self) -> None:
        class Inner(BaseModel):
            amount_cents: int
            label: str

        class Cat(BaseModel):
            kind: Literal["cat"]
            price_cents: int

        class Dog(BaseModel):
            kind: Literal["dog"]
            price_cents: float

        class Sneaky(BaseModel):
            plain_cents: int
            amounts_cents: list[int]
            by_category_cents: dict[str, int]
            nested: Inner
            nested_list: list[Inner]
            maybe_cents: int | None
            either: Union[int, str]  # noqa: UP007 - deliberately the typing.Union form
            pet: Annotated[Cat | Dog, Field(discriminator="kind")]  # emits oneOf
            fixed: tuple[str, int]  # emits prefixItems
            text_only: str

        assert numeric_paths(Sneaky.model_json_schema()) == {
            "plain_cents",
            "amounts_cents[]",
            "by_category_cents{}",
            "nested.amount_cents",
            "nested_list[].amount_cents",
            "maybe_cents",
            "either",
            "pet.price_cents",
            "fixed",
        }

    def test_detects_allof_and_type_lists_in_raw_schemas(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "combined": {"allOf": [{"$ref": "#/$defs/Money"}]},
                "nullable": {"type": ["integer", "null"]},
                "patterned": {"type": "object", "patternProperties": {".*": {"type": "number"}}},
                "safe": {"type": "string"},
            },
            "$defs": {"Money": {"type": "object", "properties": {"cents": {"type": "integer"}}}},
        }
        assert numeric_paths(schema) == {"combined.cents", "nullable", "patterned{}"}

    def test_survives_recursive_models(self) -> None:
        class Node(BaseModel):
            value_cents: int
            children: list["Node"] = []

        assert numeric_paths(Node.model_json_schema()) == {"value_cents"}


@pytest.mark.parametrize(
    "model,allowed",
    [
        (TransactionDraft, {"category_id"}),  # an id chosen from the offered list, not money
        (InsightsResult, set()),
    ],
)
def test_provider_outputs_have_no_numeric_money_fields(model, allowed: set[str]) -> None:
    assert numeric_paths(model.model_json_schema()) == allowed


# ---------------------------------------------------------------------------
# Fake provider: figures only ever come from backend rendering
# ---------------------------------------------------------------------------

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
        transaction_count=1,
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
def test_fake_output_has_no_figures_and_always_renders(summary: SpendingSummary) -> None:
    result = FakeAIProvider().generate_insights(InsightsRequest(summary=summary))

    # The only provider-written text is advice; it must contain no numeric characters at all.
    for selection in result.insights:
        assert not any(c.isnumeric() for c in selection.advice or "")
    # Raises UngroundedTextError if anything broke the rules.
    assert render_insights(result, summary)


def test_balance_is_rendered_from_the_backend_value_not_recalculated() -> None:
    # Deliberately inconsistent figures: income − expenses would be 300 000 ₸, but the backend
    # says 123 456,78 ₸. The rendered text must show the backend's figure and never "fix" it.
    summary = SpendingSummary(
        period_label="October 2026",
        total_income_cents=500_000_00,
        total_expense_cents=200_000_00,
        balance_cents=123_456_78,
        transaction_count=3,
    )
    result = FakeAIProvider().generate_insights(InsightsRequest(summary=summary))

    text = " ".join(i.message for i in render_insights(result, summary))

    assert f"surplus of {format_kzt(123_456_78)}" in text
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
