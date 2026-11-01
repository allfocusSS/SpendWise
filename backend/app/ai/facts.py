"""Backend-controlled insight sentences.

Providers do not write sentences that contain figures. They return InsightSelection items
(a typed topic such as "balance", plus optional advice). The backend then:

1. chooses the sentence from the ACTUAL figures: topic "balance" becomes balance_surplus,
   balance_deficit or balance_even depending on the sign of the backend's balance; topic
   "expense_change" becomes expense_increase/decrease/unchanged depending on the rounded change;
2. renders that sentence from a fixed template, putting each value in its fixed role;
3. validates the advice with app.ai.text_checks.check_free_text and shows it separately.

What this guarantees: every figure in a rendered sentence is a backend value in its intended role
(income in the income slot, the balance with the word matching its sign), and a provider cannot
pick a surplus sentence for a deficit or an increase sentence for a decrease.

What it does not guarantee: that the advice text is sensible or true. The advice checks reject
numbers, units, number words and listed direction claims, but the word lists are best-effort, so
advice can still claim the wrong direction in other words ("Your balance is negative." next to a
surplus). User-controlled category names are shown in quotes, exactly as the user typed them
(minus invisible characters), so they may contain digits.
"""

import unicodedata

from app.ai.schemas import (
    Insight,
    InsightSelection,
    InsightsResult,
    InsightTopic,
    SentenceId,
    SpendingSummary,
)
from app.ai.text_checks import UngroundedTextError, check_free_text
from app.core.money import format_kzt, format_percentage, rounded_percentage

__all__ = ["UngroundedTextError", "render_insights", "render_sentence", "select_sentence"]

TITLES = {
    SentenceId.NO_ACTIVITY: "No activity yet",
    SentenceId.OVERVIEW: "Overview",
    SentenceId.BALANCE_SURPLUS: "Surplus",
    SentenceId.BALANCE_DEFICIT: "Deficit",
    SentenceId.BALANCE_EVEN: "Break-even",
    SentenceId.TOP_CATEGORY: "Largest expense category",
    SentenceId.EXPENSE_INCREASE: "Expenses went up",
    SentenceId.EXPENSE_DECREASE: "Expenses went down",
    SentenceId.EXPENSE_UNCHANGED: "Expenses unchanged",
}


def select_sentence(topic: InsightTopic, summary: SpendingSummary) -> SentenceId:
    """Pick the sentence for a topic from the backend's figures (the provider cannot choose)."""
    match topic:
        case InsightTopic.OVERVIEW:
            return SentenceId.OVERVIEW
        case InsightTopic.BALANCE:
            if summary.balance_cents > 0:
                return SentenceId.BALANCE_SURPLUS
            if summary.balance_cents < 0:
                return SentenceId.BALANCE_DEFICIT
            return SentenceId.BALANCE_EVEN
        case InsightTopic.TOP_CATEGORY:
            if not summary.top_expense_categories:
                raise UngroundedTextError("top_category requested, but there are no categories")
            return SentenceId.TOP_CATEGORY
        case InsightTopic.EXPENSE_CHANGE:
            if summary.expense_change_percentage is None:
                raise UngroundedTextError("expense_change requested, but there is no comparison")
            change = rounded_percentage(summary.expense_change_percentage)
            if change > 0:
                return SentenceId.EXPENSE_INCREASE
            if change < 0:
                return SentenceId.EXPENSE_DECREASE
            return SentenceId.EXPENSE_UNCHANGED


def render_sentence(sentence_id: SentenceId, summary: SpendingSummary) -> str:
    """Fixed template per sentence id; each value goes into its own role. Formatting only."""
    match sentence_id:
        case SentenceId.NO_ACTIVITY:
            return f"There are no transactions for {summary.period_label} yet."
        case SentenceId.OVERVIEW:
            count = summary.transaction_count
            noun = "transaction" if count == 1 else "transactions"
            return (
                f"In {summary.period_label} you had income of "
                f"{format_kzt(summary.total_income_cents)} and expenses of "
                f"{format_kzt(summary.total_expense_cents)} across {count} {noun}."
            )
        case SentenceId.BALANCE_SURPLUS:
            return f"The period ended with a surplus of {format_kzt(summary.balance_cents)}."
        case SentenceId.BALANCE_DEFICIT:
            # The word carries the sign, so the magnitude is shown without one.
            return f"The period ended with a deficit of {format_kzt(abs(summary.balance_cents))}."
        case SentenceId.BALANCE_EVEN:
            return f"Income and expenses were equal; the balance is {format_kzt(0)}."
        case SentenceId.TOP_CATEGORY:
            top = summary.top_expense_categories[0]
            return (
                f"Your largest expense category was {quote_name(top.name)}: "
                f"{format_kzt(top.total_cents)}, {format_percentage(top.percentage)} of expenses."
            )
        case SentenceId.EXPENSE_INCREASE | SentenceId.EXPENSE_DECREASE:
            change = abs(summary.expense_change_percentage or 0.0)
            verb = "increased" if sentence_id is SentenceId.EXPENSE_INCREASE else "decreased"
            return (
                f"Your expenses {verb} by {format_percentage(change)} "
                "compared with the previous period."
            )
        case SentenceId.EXPENSE_UNCHANGED:
            return "Your expenses were unchanged compared with the previous period."


def quote_name(name: str) -> str:
    """Show a user-controlled name in quotes so it reads as a name, not as a backend figure.

    Invisible/control characters are removed and inner quotes replaced; the visible text is
    otherwise kept exactly as the user typed it.
    """
    visible = "".join(
        " " if c.isspace() else c
        for c in name
        if c.isspace() or unicodedata.category(c) not in ("Cf", "Cc")
    )
    visible = " ".join(visible.split()).replace("“", "'").replace("”", "'").replace('"', "'")
    return f"“{visible}”"


def render_insights(result: InsightsResult, summary: SpendingSummary) -> list[Insight]:
    """Validate a provider's selections and render them. Any violation rejects the whole result."""
    topics = [selection.topic for selection in result.insights]
    if len(topics) != len(set(topics)):
        raise UngroundedTextError("Each topic may be selected only once")
    advice = [_advice(selection) for selection in result.insights]

    if summary.transaction_count == 0:
        sentence = SentenceId.NO_ACTIVITY
        return [
            Insight(
                sentence_id=sentence,
                title=TITLES[sentence],
                message=render_sentence(sentence, summary),
            )
        ]

    insights = []
    for selection, selection_advice in zip(result.insights, advice, strict=True):
        sentence = select_sentence(selection.topic, summary)
        insights.append(
            Insight(
                sentence_id=sentence,
                title=TITLES[sentence],
                message=render_sentence(sentence, summary),
                advice=selection_advice,
            )
        )
    return insights


def _advice(selection: InsightSelection) -> str | None:
    if selection.advice is None or not selection.advice.strip():
        return None
    return check_free_text(selection.advice).strip()
