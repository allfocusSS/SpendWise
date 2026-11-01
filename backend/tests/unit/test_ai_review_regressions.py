"""Regression tests for both PR #13 reviews, run against the real provider, schemas and renderer.

Round 1: H1 (grounding), M1 (ambiguous formats), L3 (percentages).
Round 2: H1-a (Unicode numerics), H1-b (contradictions), H1-c (units/number words),
M1-a (whitespace and amount integrity), items 6-11.
"""

import math
from datetime import date

import pytest
from pydantic import ValidationError

from app.ai import FakeAIProvider
from app.ai.facts import UngroundedTextError, render_insights
from app.ai.schemas import (
    CategoryOption,
    CategoryShare,
    InsightsRequest,
    InsightsResult,
    SentenceId,
    SpendingSummary,
    TransactionDraftRequest,
)
from app.core.money import format_kzt

DEFICIT = SpendingSummary(
    period_label="October 2026",
    total_income_cents=500_000_00,
    total_expense_cents=150_000_00,
    balance_cents=-20_000_00,
    transaction_count=5,
    top_expense_categories=[CategoryShare(name="Groceries", total_cents=450_00, percentage=66.67)],
    expense_change_percentage=12.5,
)
SURPLUS = DEFICIT.model_copy(
    update={"balance_cents": 35_000_00, "expense_change_percentage": -3.25}
)


def plain(text: str) -> str:
    return text.replace("\u00a0", " ")


def provider_result(*items: dict) -> InsightsResult:
    """What a (possibly misbehaving) provider returns, validated by the real schema."""
    return InsightsResult.model_validate({"provider": "adversary", "insights": list(items)})


def rendered_text(result: InsightsResult, summary: SpendingSummary) -> str:
    return plain(
        " ".join(f"{i.message} {i.advice or ''}" for i in render_insights(result, summary))
    )


def draft(text: str):
    request = TransactionDraftRequest(
        text=text,
        categories=[
            CategoryOption(id=1, name="Transport", type="expense"),
            CategoryOption(id=9, name="Other expenses", type="expense"),
        ],
        today=date(2026, 11, 1),
    )
    return FakeAIProvider().parse_transaction(request)


# ============================================================================================
# H1-b — semantic contradictions are impossible: the backend chooses every figure sentence
# ============================================================================================


class TestDeficitDescribedAsSurplus:
    def test_provider_cannot_select_the_surplus_sentence(self) -> None:
        with pytest.raises(ValidationError):
            provider_result({"topic": "balance_surplus"})

    def test_balance_topic_renders_the_deficit_sentence(self) -> None:
        text = rendered_text(provider_result({"topic": "balance"}), DEFICIT)
        assert text.strip() == "The period ended with a deficit of 20 000 ₸."
        assert "surplus" not in text

    @pytest.mark.parametrize(
        "advice",
        [
            "Great news: you had a surplus.",
            "Great job staying in the black.",
            "Your income exceeded your expenses.",
            "You have money left over.",
            "You saved a lot this month.",
        ],
    )
    def test_advice_cannot_claim_a_surplus(self, advice: str) -> None:
        with pytest.raises(UngroundedTextError, match="direction claim"):
            render_insights(provider_result({"topic": "balance", "advice": advice}), DEFICIT)


class TestSurplusDescribedAsDeficit:
    def test_provider_cannot_select_the_deficit_sentence(self) -> None:
        with pytest.raises(ValidationError):
            provider_result({"topic": "balance_deficit"})

    def test_balance_topic_renders_the_surplus_sentence(self) -> None:
        text = rendered_text(provider_result({"topic": "balance"}), SURPLUS)
        assert text.strip() == "The period ended with a surplus of 35 000 ₸."
        assert "deficit" not in text

    @pytest.mark.parametrize("advice", ["Watch out for the deficit.", "You are in the red."])
    def test_advice_cannot_claim_a_deficit(self, advice: str) -> None:
        with pytest.raises(UngroundedTextError, match="direction claim"):
            render_insights(provider_result({"topic": "balance", "advice": advice}), SURPLUS)


class TestIncomeAndExpensesSwapped:
    def test_provider_cannot_supply_its_own_sentence_or_values(self) -> None:
        for extra in (
            {"template": "You earned {expenses} and spent {income}."},
            {"message": "You earned 150 000 ₸ and spent 500 000 ₸."},
            {"income_cents": 150_000_00},
        ):
            with pytest.raises(ValidationError):
                provider_result({"topic": "overview", **extra})

    def test_overview_puts_each_value_in_its_own_role(self) -> None:
        text = rendered_text(provider_result({"topic": "overview"}), DEFICIT)
        assert "income of 500 000 ₸ and expenses of 150 000 ₸" in text
        assert "income of 150 000 ₸" not in text

    def test_advice_cannot_reference_fact_placeholders(self) -> None:
        with pytest.raises(UngroundedTextError, match="placeholders"):
            render_insights(
                provider_result({"topic": "overview", "advice": "You earned {expenses}."}),
                DEFICIT,
            )


class TestIncreaseDescribedAsDecrease:
    def test_provider_cannot_select_a_direction(self) -> None:
        for identifier in ("expense_decrease", "expense_increase", "expense_unchanged"):
            with pytest.raises(ValidationError):
                provider_result({"topic": identifier})

    def test_change_topic_follows_the_backend_value(self) -> None:
        increase = rendered_text(provider_result({"topic": "expense_change"}), DEFICIT)
        decrease = rendered_text(provider_result({"topic": "expense_change"}), SURPLUS)
        assert "Your expenses increased by 12.5%" in increase
        assert "Your expenses decreased by 3.25%" in decrease

    @pytest.mark.parametrize("advice", ["Your spending went down.", "Costs decreased nicely."])
    def test_advice_cannot_claim_the_opposite_direction(self, advice: str) -> None:
        with pytest.raises(UngroundedTextError, match="direction claim"):
            render_insights(provider_result({"topic": "expense_change", "advice": advice}), DEFICIT)


@pytest.mark.parametrize(
    "identifier", ["made_up", "BALANCE", "balance ", "", "no_activity", "income", None, 3]
)
def test_invalid_template_identifiers_are_rejected(identifier) -> None:
    with pytest.raises(ValidationError):
        provider_result({"topic": identifier})


def test_fake_provider_output_renders_correctly_for_both_signs() -> None:
    provider = FakeAIProvider()
    for summary, expected in (
        (DEFICIT, SentenceId.BALANCE_DEFICIT),
        (SURPLUS, SentenceId.BALANCE_SURPLUS),
    ):
        result = provider.generate_insights(InsightsRequest(summary=summary))
        assert expected in [i.sentence_id for i in render_insights(result, summary)]


# ============================================================================================
# H1-a / H1-c — Unicode numerics, units and number words in advice (all review bypasses)
# ============================================================================================


@pytest.mark.parametrize(
    "advice",
    [
        # round-2 H1-a
        "Cut groceries by ½ next month.",
        "About ¾ of it went to food.",
        "Keep this up for Ⅻ weeks.",
        "Ⅳ tips for you.",
        "You could keep 五千 aside.",
        # round-2 H1-c number words
        "That is a trillion times better.",
        "Spend a quarter less.",
        "Cut a third of it.",
        "Почти миллиард.",
        "Отложите пятьдесят.",
        "About a thou\u200bsand more.",
        "About a thоusand more.",
        # round-2 H1-c units
        "Keep a few ％ aside.",
        "Keep a few \u066a aside.",
        "Keep a few \u2030 aside.",
        "Keep a few ¥ ₹ ₩ aside.",
        "You could save a little теңге per day.",
        "You could save a little tg per day.",
        # round-1 examples
        "Great news: you saved 20 000 ₸ this month.",
        "You received 150 000 ₸ and spent 500 000 ₸.",
        "You could save 5 ₸ per day.",
        "Groceries cost 2026 ₸.",
        "Expenses grew by 12.5 ₸.",
        "You spent fifty thousand tenge on coffee.",
        "Your spending doubled; cut it in half.",
        "Income was 500K ₸ and 66.67 million ₸ is possible.",
    ],
)
def test_every_review_bypass_is_rejected_in_advice(advice: str) -> None:
    with pytest.raises(UngroundedTextError):
        render_insights(provider_result({"topic": "overview", "advice": advice}), DEFICIT)


# ============================================================================================
# M1 / M1-a / items 6 and 11 — the fake parser never truncates, changes or guesses an amount
# ============================================================================================


@pytest.mark.parametrize(
    "text,amount",
    [
        ("taxi 2\u202f500 ₸", "2\u202f500"),  # narrow no-break space: whole amount, verbatim
        ("taxi 2\u2009500 ₸", "2\u2009500"),  # thin space
        ("taxi 2\u2007500 ₸", "2\u2007500"),  # figure space
        ("taxi 2\u00a0500 ₸", "2\u00a0500"),
        ("rent 450 000 tenge", "450 000"),
        ("taxi 12.50", "12.50"),
        ("2 coffees for ₸1500", "1500"),  # currency prefix
        ("KZT 900 taxi", "900"),
        ("5000tg taxi", "5000"),
        ("taxi 900 теңге", "900"),
        ("2 coffees 1500 tenge", "1500"),
    ],
)
def test_unambiguous_amounts_are_returned_whole_and_verbatim(text: str, amount: str) -> None:
    result = draft(text)
    assert result.amount_text == amount
    assert result.amount_text in text


@pytest.mark.parametrize(
    "text,note",
    [
        ("taxi 2\t500 ₸", "unclear separator"),  # tab
        ("taxi 2  500 ₸", "unclear separator"),  # double space
        ("rent 12 34 tenge", "malformed digit grouping"),
        ("concert tickets for 2027 5000", "malformed digit grouping"),
        ("rent 450,000 tenge", "ambiguous"),
        ("rent 1,234,567 tenge", "ambiguous"),
        ("rent 12.500 tenge", "ambiguous"),
        ("taxi ٤٥٠ tenge", "Only the digits 0-9"),
        ("taxi ４５０ tenge", "Only the digits 0-9"),
        ("taxi 4٥0 tenge", "Only the digits 0-9"),
        ("iphone 15 for 500000", "Several possible amounts"),  # unrelated earlier number
        ("500 tenge and 300 tenge", "Several possible amounts"),
    ],
)
def test_ambiguous_or_malformed_amounts_are_left_empty_with_a_note(text: str, note: str) -> None:
    result = draft(text)
    assert result.amount_text is None  # never a partial or altered amount
    assert any(note in n for n in result.notes), result.notes


def test_before_the_fix_these_were_silently_truncated() -> None:
    # Review evidence: "2\u202f500 ₸" → "500", "12 34 tenge" → "34", "450,000" → "000".
    for text in ("taxi 2\u202f500 ₸", "rent 12 34 tenge", "rent 450,000 tenge"):
        assert draft(text).amount_text not in ("500", "34", "000", "450,00")


MULTIPLIER = "multipliers are not converted"
FOREIGN = "Only tenge is supported"
CALCULATION = "calculation, range or percentage"
NUMERAL = "Only the digits 0-9"
JOINED = "written together with other characters"


@pytest.mark.parametrize(
    "text,note",
    [
        # Second-review evidence: each of these used to return only the digits, with no note.
        ("taxi 1.5k tenge", MULTIPLIER),  # was "1.5"
        ("rent 5 млн тенге", MULTIPLIER),  # was "5"
        ("rent 300 тыс тенге", MULTIPLIER),  # was "300"
        ("lunch 2к тг", MULTIPLIER),  # was "2"
        ("dinner $50", FOREIGN),  # was "50"
        ("dinner 50 USD", FOREIGN),  # was "50"
        ("50 рублей", FOREIGN),  # was "50"
        ("split 3000/2 tenge", CALCULATION),  # was "2"
        ("taxi 1500-2000 tenge", CALCULATION),  # was "2000"
        ("pizza 1500½ tenge", NUMERAL),  # was "1500"
    ],
)
def test_amounts_whose_meaning_is_changed_are_left_empty_with_a_note(text: str, note: str) -> None:
    result = draft(text)
    assert result.amount_text is None
    assert any(note in n for n in result.notes), result.notes


@pytest.mark.parametrize(
    "text,note",
    [
        # Multipliers: attached letters, words with or without a dot, other languages
        ("taxi 2500k", MULTIPLIER),
        ("taxi 1.5 k tenge", MULTIPLIER),
        ("rent 1,5kk tenge", MULTIPLIER),
        ("rent 300 тыс. тг", MULTIPLIER),
        ("rent 2 тысячи тенге", MULTIPLIER),
        ("rent 1,5 млн", MULTIPLIER),
        ("rent 2 млрд тенге", MULTIPLIER),
        ("rent 5 мың теңге", MULTIPLIER),
        ("rent 2.5 thousand tenge", MULTIPLIER),
        ("rent 3 million tenge", MULTIPLIER),
        ("rent 3 mln", MULTIPLIER),
        ("laptop 2 grand", MULTIPLIER),
        ("rent 3 MLN TENGE", MULTIPLIER),
        # Other currencies: any currency symbol except ₸, and common currency words
        ("dinner €40", FOREIGN),
        ("dinner £40", FOREIGN),
        ("dinner 40 ₽", FOREIGN),
        ("dinner 40 eur", FOREIGN),
        ("dinner 40 dollars", FOREIGN),
        ("dinner 40 руб.", FOREIGN),
        ("dinner 40 долларов", FOREIGN),
        ("dinner 1500 tenge, about $3", FOREIGN),
        # Calculations, ranges, multiplication and percentages
        ("split 1500 + 500 tenge", CALCULATION),
        ("taxi 1500 - 2000 tenge", CALCULATION),
        ("2x1500 tenge", CALCULATION),
        ("2 × 1500 tenge", CALCULATION),
        ("2 х 1500 тенге", CALCULATION),  # Cyrillic х
        ("3*500 tenge", CALCULATION),
        ("coffee 1500 tenge x2", CALCULATION),
        ("2x coffee 1500 tenge", CALCULATION),
        ("tip 10% of 5000 tenge", CALCULATION),
        ("tip 10％ of 5000 tenge", CALCULATION),  # fullwidth percent
        ("tip 10 percent of 5000 tenge", CALCULATION),
        ("tip 10 процентов от 5000 тенге", CALCULATION),
        # Non-ASCII numerals anywhere, not only digits
        ("pizza ½ 1500 tenge", NUMERAL),
        ("taxi 1500 tenge Ⅻ", NUMERAL),
        ("taxi 1500⅓ tenge", NUMERAL),  # ⅓ is numeric but not a digit
    ],
)
def test_nearby_bypasses_are_left_empty_with_a_note(text: str, note: str) -> None:
    result = draft(text)
    assert result.amount_text is None
    assert any(note in n for n in result.notes), result.notes


@pytest.mark.parametrize(
    "text,note",
    [
        # Final-review evidence: each of these used to return only part of the amount.
        ("taxi 1'500 tenge", JOINED),  # was "500" (apostrophe grouping)
        ("taxi 1’500 tenge", JOINED),  # was "500" (right single quote)
        ("taxi 1\u200b500 tenge", JOINED),  # was "500" (zero-width space)
        ("taxi 1500٫50 tenge", JOINED),  # was "50" (Arabic decimal separator)
        ("taxi 1500–2000 tenge", JOINED),  # was "2000" (en dash)
        ("taxi 1500—2000 tenge", JOINED),  # was "2000" (em dash)
        ("split 3000∕2 tenge", JOINED),  # was "2" (division slash)
        ("split 1500＋500 tenge", JOINED),  # was "500" (fullwidth plus)
        ("taxi 1.5\u200bk tenge", JOINED),  # was "1.5" (zero-width space before "k")
        ("rent 5\u200bмлн тенге", JOINED),  # was "5"
        ("dinner usd50", FOREIGN),  # was "50"
        ("dinner eur40", FOREIGN),  # was "40"
        # The same structural rule covers characters nobody listed.
        ("taxi 1٬500 tenge", JOINED),  # Arabic thousands separator
        ("taxi 1，500 tenge", JOINED),  # fullwidth comma
        ("taxi 1_500 tenge", JOINED),
        ("taxi 1·500 tenge", JOINED),  # middle dot
        ("taxi 1\u2060500 tenge", JOINED),  # word joiner
        ("taxi 1\u00ad500 tenge", JOINED),  # soft hyphen
        ("taxi 1500−2000 tenge", JOINED),  # minus sign
        ("taxi 1500~2000 tenge", JOINED),
        ("taxi 1500...2000 tenge", JOINED),
        ("phone iphone15 tenge", JOINED),  # a model number is not an amount
        ("taxi 1500 – 2000 tenge", CALCULATION),  # a symbol standing alone between numbers
        ("split 3000 ∕ 2 tenge", CALCULATION),
        ("dinner 50usd", FOREIGN),
        ("dinner 100руб", FOREIGN),
        ("taxi 1.5k tenge", MULTIPLIER),
        ("rent 5млн тенге", MULTIPLIER),
    ],
)
def test_amount_must_stand_alone_to_be_returned(text: str, note: str) -> None:
    result = draft(text)
    assert result.amount_text is None
    assert any(note in n for n in result.notes), result.notes


def test_invisible_characters_are_shown_in_the_note() -> None:
    [note] = [n for n in draft("taxi 1\u200b500 tenge").notes if "together" in n]
    assert "1<U+200B>500" in note


@pytest.mark.parametrize(
    "text,amount",
    [
        ("₸1500", "1500"),
        ("5000tg taxi", "5000"),
        ("1500тенге taxi", "1500"),
        ("2026-10-20 dentist 8000", "8000"),  # an ISO date is not a range
        ("transport card top-up 2000", "2000"),  # hyphen between words
        ("рубашка 5000 тенге", "5000"),  # "рубашка" (shirt) is not "рубль"
        ("подарок 1500 к празднику", "1500"),  # a lone Cyrillic "к" is the word "to"
        ("taxi -500 tenge", "500"),  # unchanged: the transaction type gives the direction
        ("taxi 1500 tenge", "1500"),
        ("KZT1500", "1500"),
        ("(₸1500)", "1500"),
        ("«1500 тенге»", "1500"),
        ("taxi 1500тг.", "1500"),
        ("taxi 2\u00a0500 ₸", "2\u00a0500"),
        ("Magnum 12 345,50 ₸", "12 345,50"),
        ("taxi: 2500, thanks!", "2500"),
    ],
)
def test_ordinary_text_around_an_amount_is_not_mistaken_for_a_modifier(
    text: str, amount: str
) -> None:
    result = draft(text)
    assert result.amount_text == amount
    assert not any("amount" in n.lower() for n in result.notes), result.notes


# ============================================================================================
# L3 / items 7 and 8 — schema bounds and backend formatting
# ============================================================================================


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -40.0, 250.0])
def test_category_share_must_be_between_0_and_100(value: float) -> None:
    with pytest.raises(ValidationError):
        CategoryShare(name="Groceries", total_cents=100, percentage=value)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -100.01, 1_000_000.01, 1e300])
def test_expense_change_rejects_non_finite_and_unreasonable_values(value: float) -> None:
    with pytest.raises(ValidationError):
        DEFICIT.model_validate({**DEFICIT.model_dump(), "expense_change_percentage": value})


@pytest.mark.parametrize("value", [-100.0, -40.0, 0.0, 250.0, 1_000_000.0])
def test_expense_change_accepts_reasonable_values(value: float) -> None:
    summary = DEFICIT.model_validate({**DEFICIT.model_dump(), "expense_change_percentage": value})
    assert summary.expense_change_percentage == value


@pytest.mark.parametrize("field", ["total_income_cents", "total_expense_cents"])
def test_negative_income_or_expense_totals_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        DEFICIT.model_validate({**DEFICIT.model_dump(), field: -1})


def test_negative_category_total_is_rejected_but_negative_balance_is_allowed() -> None:
    with pytest.raises(ValidationError):
        CategoryShare(name="Groceries", total_cents=-1, percentage=1.0)
    assert DEFICIT.balance_cents < 0


def test_negative_zero_share_renders_as_zero() -> None:
    summary = DEFICIT.model_copy(
        update={"top_expense_categories": [CategoryShare(name="X", total_cents=0, percentage=-0.0)]}
    )
    text = rendered_text(provider_result({"topic": "top_category"}), summary)
    assert "0% of expenses" in text
    assert "-0%" not in text


def test_tiny_change_is_unchanged_not_a_zero_percent_increase() -> None:
    summary = DEFICIT.model_copy(update={"expense_change_percentage": 0.004})
    text = rendered_text(provider_result({"topic": "expense_change"}), summary)
    assert text.strip() == "Your expenses were unchanged compared with the previous period."


def test_backend_balance_is_rendered_even_when_inconsistent() -> None:
    # income − expenses would be 350 000 ₸; the backend says -20 000 ₸. Nothing recomputes it.
    text = rendered_text(provider_result({"topic": "balance"}), DEFICIT)
    assert plain(format_kzt(350_000_00)) not in text
    assert "deficit of 20 000 ₸" in text
