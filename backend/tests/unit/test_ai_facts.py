"""Money formatting, amount rules and backend sentence rendering (core/money.py, ai/facts.py)."""

import pytest

from app.ai.facts import (
    TITLES,
    UngroundedTextError,
    quote_name,
    render_insights,
    render_sentence,
    select_sentence,
)
from app.ai.schemas import (
    CategoryShare,
    InsightSelection,
    InsightsResult,
    InsightTopic,
    SentenceId,
    SpendingSummary,
)
from app.core.money import amount_text_problem, format_kzt, format_percentage, is_unambiguous_amount


def plain(text: str) -> str:
    return text.replace("\u00a0", " ")


def make_summary(**overrides) -> SpendingSummary:
    values = {
        "period_label": "October 2026",
        "total_income_cents": 500_000_50,
        "total_expense_cents": 150_000_00,
        "balance_cents": 350_000_50,
        "transaction_count": 5,
        "top_expense_categories": [
            CategoryShare(name="Groceries", total_cents=100_000_00, percentage=66.67)
        ],
        "expense_change_percentage": 12.5,
    }
    return SpendingSummary(**{**values, **overrides})


def results(*topics: InsightTopic, advice: str | None = None) -> InsightsResult:
    return InsightsResult(
        provider="test", insights=[InsightSelection(topic=t, advice=advice) for t in topics]
    )


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
        assert plain(format_kzt(tiyn)) == expected

    def test_uses_non_breaking_spaces(self) -> None:
        assert format_kzt(250_000) == "2\u00a0500\u00a0₸"

    @pytest.mark.parametrize("value", [12.5, "100", True, None])
    def test_rejects_non_integers(self, value) -> None:
        with pytest.raises(TypeError):
            format_kzt(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        (66.67, "66.67%"),
        (100.0, "100%"),
        (33.3, "33.3%"),
        (-5.0, "-5%"),
        (-0.0, "0%"),  # negative zero is never shown
        (0.004, "0%"),
        (-0.004, "0%"),
        (0.005, "0.01%"),  # half-up
        (12.345, "12.35%"),
    ],
)
def test_format_percentage(value: float, expected: str) -> None:
    assert format_percentage(value) == expected


class TestAmountRules:
    @pytest.mark.parametrize(
        "text",
        [
            "2500",
            "2 500",
            "2\u00a0500",
            "2\u202f500",  # narrow no-break space
            "2\u2009500",  # thin space
            "2\u2007500",  # figure space
            "2 500,50",
            "19.99",
            "1,5",
            "1 234 567",
            "0.01",
        ],
    )
    def test_accepts_unambiguous_formats(self, text: str) -> None:
        assert is_unambiguous_amount(text)

    @pytest.mark.parametrize(
        "text,reason",
        [
            ("450,000", "ambiguous"),
            ("1,234,567", "ambiguous"),
            ("12.500", "ambiguous"),
            ("1.234.567", "ambiguous"),
            ("1.500,50", "ambiguous"),
            ("1,500.50", "ambiguous"),
            ("12 34", "malformed digit grouping"),
            ("1234 567", "malformed digit grouping"),
            ("1 2 3", "malformed digit grouping"),
            ("2\t500", "unclear separator"),
            ("2  500", "unclear separator"),
            ("٤٥٠", "non-ASCII digits"),
            ("４５０", "non-ASCII digits"),
            ("4٥0", "non-ASCII digits"),
            ("", "ambiguous"),
            ("-5", "ambiguous"),
        ],
    )
    def test_rejects_with_a_reason(self, text: str, reason: str) -> None:
        assert reason in (amount_text_problem(text) or "")
        assert not is_unambiguous_amount(text)


class TestSentenceSelection:
    @pytest.mark.parametrize(
        "balance,sentence",
        [
            (1, SentenceId.BALANCE_SURPLUS),
            (-1, SentenceId.BALANCE_DEFICIT),
            (0, SentenceId.BALANCE_EVEN),
        ],
    )
    def test_balance_sentence_follows_the_backend_sign(self, balance: int, sentence) -> None:
        assert (
            select_sentence(InsightTopic.BALANCE, make_summary(balance_cents=balance)) == sentence
        )

    @pytest.mark.parametrize(
        "change,sentence",
        [
            (12.5, SentenceId.EXPENSE_INCREASE),
            (-3.25, SentenceId.EXPENSE_DECREASE),
            (0.0, SentenceId.EXPENSE_UNCHANGED),
            (0.004, SentenceId.EXPENSE_UNCHANGED),  # rounds to 0: never "a 0% increase"
            (-0.004, SentenceId.EXPENSE_UNCHANGED),
            (0.005, SentenceId.EXPENSE_INCREASE),
        ],
    )
    def test_change_sentence_follows_the_rounded_backend_value(self, change, sentence) -> None:
        summary = make_summary(expense_change_percentage=change)
        assert select_sentence(InsightTopic.EXPENSE_CHANGE, summary) == sentence

    def test_unavailable_topics_are_rejected(self) -> None:
        with pytest.raises(UngroundedTextError, match="no categories"):
            select_sentence(InsightTopic.TOP_CATEGORY, make_summary(top_expense_categories=[]))
        with pytest.raises(UngroundedTextError, match="no comparison"):
            select_sentence(
                InsightTopic.EXPENSE_CHANGE, make_summary(expense_change_percentage=None)
            )


class TestRenderSentence:
    @pytest.mark.parametrize(
        "sentence,overrides,expected",
        [
            (
                SentenceId.OVERVIEW,
                {},
                "In October 2026 you had income of 500 000,50 ₸ and expenses of 150 000 ₸ "
                "across 5 transactions.",
            ),
            (SentenceId.OVERVIEW, {"transaction_count": 1}, "across 1 transaction."),
            (SentenceId.BALANCE_SURPLUS, {}, "The period ended with a surplus of 350 000,50 ₸."),
            (
                SentenceId.BALANCE_DEFICIT,
                {"balance_cents": -20_000_00},
                "The period ended with a deficit of 20 000 ₸.",
            ),
            (
                SentenceId.BALANCE_EVEN,
                {"balance_cents": 0},
                "Income and expenses were equal; the balance is 0 ₸.",
            ),
            (
                SentenceId.TOP_CATEGORY,
                {},
                "Your largest expense category was “Groceries”: 100 000 ₸, 66.67% of expenses.",
            ),
            (
                SentenceId.EXPENSE_INCREASE,
                {},
                "Your expenses increased by 12.5% compared with the previous period.",
            ),
            (
                SentenceId.EXPENSE_DECREASE,
                {"expense_change_percentage": -3.25},
                "Your expenses decreased by 3.25% compared with the previous period.",
            ),
            (
                SentenceId.EXPENSE_UNCHANGED,
                {"expense_change_percentage": 0.0},
                "Your expenses were unchanged compared with the previous period.",
            ),
            (SentenceId.NO_ACTIVITY, {}, "There are no transactions for October 2026 yet."),
        ],
    )
    def test_fixed_templates(self, sentence, overrides, expected: str) -> None:
        assert expected in plain(render_sentence(sentence, make_summary(**overrides)))

    def test_every_sentence_has_a_title(self) -> None:
        assert set(TITLES) == set(SentenceId)


class TestQuoteName:
    def test_user_names_are_quoted_and_invisible_characters_removed(self) -> None:
        assert quote_name("Groceries") == "“Groceries”"
        assert quote_name("Bonus +1 000 000 ₸ {income}") == "“Bonus +1 000 000 ₸ {income}”"
        assert quote_name("Ca\u200bfe\n\tbar") == "“Cafe bar”"
        assert quote_name('Say “hi” "now"') == "“Say 'hi' 'now'”"

    def test_name_with_figures_is_rendered_literally_inside_quotes(self) -> None:
        summary = make_summary(
            top_expense_categories=[
                CategoryShare(name="Bonus +1 000 000 ₸ {income}", total_cents=1_00, percentage=1.0)
            ]
        )
        text = plain(render_sentence(SentenceId.TOP_CATEGORY, summary))
        assert text == (
            "Your largest expense category was “Bonus +1 000 000 ₸ {income}”: 1 ₸, 1% of expenses."
        )


class TestRenderInsights:
    def test_renders_selected_topics_in_order_with_advice(self) -> None:
        rendered = render_insights(
            results(InsightTopic.BALANCE, InsightTopic.OVERVIEW, advice="Plan ahead."),
            make_summary(),
        )
        assert [i.sentence_id for i in rendered] == [
            SentenceId.BALANCE_SURPLUS,
            SentenceId.OVERVIEW,
        ]
        assert [i.title for i in rendered] == ["Surplus", "Overview"]
        assert all(i.advice == "Plan ahead." for i in rendered)

    def test_blank_advice_becomes_none(self) -> None:
        [insight] = render_insights(results(InsightTopic.OVERVIEW, advice="   "), make_summary())
        assert insight.advice is None

    def test_no_activity_replaces_selections_but_advice_is_still_checked(self) -> None:
        empty = make_summary(
            total_income_cents=0,
            total_expense_cents=0,
            balance_cents=0,
            transaction_count=0,
            top_expense_categories=[],
            expense_change_percentage=None,
        )
        [insight] = render_insights(results(InsightTopic.BALANCE), empty)
        assert insight.sentence_id == SentenceId.NO_ACTIVITY
        with pytest.raises(UngroundedTextError):
            render_insights(results(InsightTopic.BALANCE, advice="You saved a lot."), empty)

    def test_duplicate_topics_are_rejected(self) -> None:
        with pytest.raises(UngroundedTextError, match="only once"):
            render_insights(results(InsightTopic.BALANCE, InsightTopic.BALANCE), make_summary())

    def test_one_bad_advice_rejects_the_whole_result(self) -> None:
        result = InsightsResult(
            provider="test",
            insights=[
                InsightSelection(topic=InsightTopic.OVERVIEW, advice="Plan ahead."),
                InsightSelection(topic=InsightTopic.BALANCE, advice="Save ½ of it."),
            ],
        )
        with pytest.raises(UngroundedTextError):
            render_insights(result, make_summary())

    def test_empty_selection_renders_nothing(self) -> None:
        assert render_insights(results(), make_summary()) == []
