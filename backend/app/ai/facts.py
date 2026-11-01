"""Backend-calculated facts the AI may quote, and a check that AI text quotes nothing else.

Providers receive figures already formatted for display ("450 000 ₸", "66.67%") and may only
repeat them. `find_ungrounded_numbers` flags any number in AI text that is not one of those
facts, so an invented or recalculated figure can be rejected before a user sees it.
"""

import re

from app.ai.schemas import SpendingSummary
from app.core.money import format_kzt, format_percentage


def summary_facts(summary: SpendingSummary) -> dict[str, str]:
    """Display strings for every figure in the summary. No arithmetic: formatting only."""
    facts = {
        "period": summary.period_label,
        "income": format_kzt(summary.total_income_cents),
        "expenses": format_kzt(summary.total_expense_cents),
        "balance": format_kzt(summary.balance_cents),
        "transaction_count": str(summary.transaction_count),
    }
    for rank, category in enumerate(summary.top_expense_categories, start=1):
        facts[f"top_{rank}_name"] = category.name
        facts[f"top_{rank}_total"] = format_kzt(category.total_cents)
        facts[f"top_{rank}_percentage"] = format_percentage(category.percentage)
    if summary.expense_change_percentage is not None:
        sign = "+" if summary.expense_change_percentage > 0 else ""
        facts["expense_change"] = sign + format_percentage(summary.expense_change_percentage)
    return facts


# A number, optionally with thousands groups ("450 000", "1 234 567") and decimals ("12,50").
_NUMBER = re.compile(r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?")


def extract_numbers(text: str) -> set[str]:
    """Normalised numbers in `text`.

    "450 000 ₸" → "450000", "12,50" → "12.5", "66.67%" → "66.67".
    """
    numbers = set()
    for match in _NUMBER.findall(text):
        number = re.sub(r"[ \u00a0\u202f]", "", match).replace(",", ".")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        numbers.add(number)
    return numbers


def find_ungrounded_numbers(text: str, facts: dict[str, str]) -> set[str]:
    """Numbers in `text` that do not appear in any fact. Empty set = fully grounded."""
    allowed = set().union(*(extract_numbers(value) for value in facts.values()))
    return extract_numbers(text) - allowed
