"""Money display formatting and the grounding check for AI text."""

import pytest

from app.ai.facts import extract_numbers, find_ungrounded_numbers, summary_facts
from app.ai.schemas import CategoryShare, SpendingSummary
from app.core.money import format_kzt, format_percentage


class TestFormatKzt:
    @pytest.mark.parametrize(
        "tiyn,expected",
        [
            (250_000, "2 500 ₸"),
            (250_050, "2 500,50 ₸"),
            (1, "0,01 ₸"),
            (0, "0 ₸"),
            (-123_455, "-1 234,55 ₸"),
            (1_000_000_000_000, "10 000 000 000 ₸"),
        ],
    )
    def test_matches_frontend_format(self, tiyn: int, expected: str) -> None:
        assert format_kzt(tiyn).replace("\u00a0", " ") == expected

    def test_uses_non_breaking_spaces(self) -> None:
        assert format_kzt(250_000) == "2\u00a0500\u00a0₸"

    @pytest.mark.parametrize("value", [12.5, "100", True, None])
    def test_rejects_non_integers(self, value) -> None:
        with pytest.raises(TypeError):
            format_kzt(value)


@pytest.mark.parametrize(
    "value,expected", [(66.67, "66.67%"), (100.0, "100%"), (33.3, "33.3%"), (-5.0, "-5%")]
)
def test_format_percentage(value: float, expected: str) -> None:
    assert format_percentage(value) == expected


class TestExtractNumbers:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("spent 450 000 ₸", {"450000"}),
            ("spent 450\u00a0000\u00a0₸", {"450000"}),
            ("12,50 and 12.50", {"12.5"}),
            ("66.67% of 3 categories", {"66.67", "3"}),
            ("October 2026", {"2026"}),
            ("no numbers here", set()),
        ],
    )
    def test_normalises(self, text: str, expected: set[str]) -> None:
        assert extract_numbers(text) == expected


class TestGrounding:
    facts = {"income": "450\u00a0000\u00a0₸", "share": "66.67%", "period": "October 2026"}

    def test_quoted_facts_are_grounded(self) -> None:
        text = "In October 2026 you earned 450 000 ₸; groceries were 66,67%."
        assert find_ungrounded_numbers(text, self.facts) == set()

    def test_invented_number_is_flagged(self) -> None:
        assert find_ungrounded_numbers("You could save 50 000 ₸.", self.facts) == {"50000"}

    def test_recalculated_number_is_flagged(self) -> None:
        # e.g. an AI "helpfully" computing a monthly average the backend never provided
        assert find_ungrounded_numbers("About 15 000 ₸ per day.", self.facts) == {"15000"}


def test_summary_facts_are_formatted_backend_values() -> None:
    summary = SpendingSummary(
        period_label="October 2026",
        total_income_cents=500_000_50,
        total_expense_cents=150_000_00,
        balance_cents=350_000_50,
        transaction_count=5,
        top_expense_categories=[CategoryShare(name="Groceries", total_cents=1_00, percentage=0.5)],
        expense_change_percentage=-3.25,
    )

    facts = {k: v.replace("\u00a0", " ") for k, v in summary_facts(summary).items()}

    assert facts == {
        "period": "October 2026",
        "income": "500 000,50 ₸",
        "expenses": "150 000 ₸",
        "balance": "350 000,50 ₸",
        "transaction_count": "5",
        "top_1_name": "Groceries",
        "top_1_total": "1 ₸",
        "top_1_percentage": "0.5%",
        "expense_change": "-3.25%",
    }
