"""FakeAIProvider: deterministic, offline, and useful for local development."""

import socket
from datetime import date

import pytest

from app.ai import AIProvider, FakeAIProvider
from app.ai.facts import render_insights
from app.ai.schemas import (
    CategoryOption,
    CategoryShare,
    InsightsRequest,
    InsightTopic,
    SentenceId,
    SpendingSummary,
    TransactionDraftRequest,
)

NBSP = "\u00a0"
TODAY = date(2026, 11, 1)
CATEGORIES = [
    CategoryOption(id=1, name="Groceries", type="expense"),
    CategoryOption(id=2, name="Transport", type="expense"),
    CategoryOption(id=3, name="Restaurants & cafes", type="expense"),
    CategoryOption(id=4, name="Other expenses", type="expense"),
    CategoryOption(id=10, name="Salary", type="income"),
    CategoryOption(id=11, name="Other income", type="income"),
]


def draft(text: str, categories: list[CategoryOption] = CATEGORIES):
    request = TransactionDraftRequest(text=text, categories=categories, today=TODAY)
    return FakeAIProvider().parse_transaction(request)


def summary(**overrides) -> SpendingSummary:
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


def insights(**overrides):
    return FakeAIProvider().generate_insights(InsightsRequest(summary=summary(**overrides)))


def test_implements_the_provider_protocol() -> None:
    provider = FakeAIProvider()
    assert isinstance(provider, AIProvider)
    assert provider.name == "fake"


class TestDeterminism:
    @pytest.mark.parametrize(
        "text", ["taxi 2500 yesterday", "salary 450 000", "lunch with friends", "2 500,50 ₸"]
    )
    def test_same_draft_input_gives_same_output(self, text: str) -> None:
        first = draft(text)
        # A fresh provider instance must not change anything either.
        assert draft(text) == first
        assert draft(text).model_dump() == first.model_dump()

    def test_same_summary_gives_same_insights(self) -> None:
        assert insights() == insights()

    def test_category_order_does_not_change_the_choice(self) -> None:
        assert draft("taxi 900").category_id == draft("taxi 900", CATEGORIES[::-1]).category_id


class TestParseTransaction:
    @pytest.mark.parametrize(
        "text,amount_text,type_,category_id,occurred_on,description",
        [
            ("taxi 2500 yesterday", "2500", "expense", 2, date(2026, 10, 31), "Taxi"),
            ("Magnum groceries 12 345,50 ₸", "12 345,50", "expense", 1, TODAY, "Magnum groceries"),
            ("2 coffees 1500 tenge", "1500", "expense", 3, TODAY, "2 coffees"),
            ("salary 450 000", "450 000", "income", 10, TODAY, "Salary"),
            ("2026-10-20 dentist 8000", "8000", "expense", 4, date(2026, 10, 20), "Dentist"),
            (
                "got paid for a gift card 3000",
                "3000",
                "income",
                11,
                TODAY,
                "Got paid for a gift card",
            ),
        ],
    )
    def test_examples(self, text, amount_text, type_, category_id, occurred_on, description):
        result = draft(text)

        assert result.amount_text == amount_text
        assert result.type == type_
        assert result.category_id == category_id
        assert result.occurred_on == occurred_on
        assert result.description == description
        assert result.notes == []

    def test_missing_amount_is_reported_not_invented(self) -> None:
        result = draft("lunch with friends")

        assert result.amount_text is None
        assert "No amount found; please enter it." in result.notes

    def test_only_offered_categories_are_used(self) -> None:
        offered = [CategoryOption(id=7, name="Transport", type="expense")]

        assert draft("taxi 900", offered).category_id == 7
        # No matching category and no "Other expenses": null plus a note, never a made-up id.
        result = draft("cinema 3000", offered)
        assert result.category_id is None
        assert "No matching expense category; please choose one." in result.notes

    def test_category_name_in_text_wins(self) -> None:
        assert draft("transport card top-up 2000").category_id == 2

    def test_description_falls_back_to_category_name(self) -> None:
        assert draft("salary 450000").description == "Salary"
        assert draft("2500").description == "Other expenses"


class TestGenerateInsights:
    def test_returns_typed_topic_selections_only(self) -> None:
        result = insights()

        assert [(i.topic, i.advice) for i in result.insights] == [
            (InsightTopic.OVERVIEW, None),
            (InsightTopic.BALANCE, None),
            (
                InsightTopic.TOP_CATEGORY,
                "A monthly limit for this category can help you plan ahead.",
            ),
            (InsightTopic.EXPENSE_CHANGE, None),
        ]

    def test_rendered_text_shows_backend_figures(self) -> None:
        rendered = render_insights(insights(), summary())

        assert [(i.sentence_id, i.message.replace(NBSP, " ")) for i in rendered] == [
            (
                SentenceId.OVERVIEW,
                "In October 2026 you had income of 500 000,50 ₸ and expenses of 150 000 ₸ "
                "across 5 transactions.",
            ),
            (SentenceId.BALANCE_SURPLUS, "The period ended with a surplus of 350 000,50 ₸."),
            (
                SentenceId.TOP_CATEGORY,
                "Your largest expense category was “Groceries”: 100 000 ₸, 66.67% of expenses.",
            ),
            (
                SentenceId.EXPENSE_INCREASE,
                "Your expenses increased by 12.5% compared with the previous period.",
            ),
        ]

    def test_reports_the_provider(self) -> None:
        assert insights().provider == "fake"

    def test_empty_period_selects_nothing_and_backend_renders_no_activity(self) -> None:
        empty = {
            "total_income_cents": 0,
            "total_expense_cents": 0,
            "balance_cents": 0,
            "transaction_count": 0,
            "top_expense_categories": [],
            "expense_change_percentage": None,
        }
        result = insights(**empty)

        assert result.insights == []
        [rendered] = render_insights(result, summary(**empty))
        assert rendered.sentence_id == SentenceId.NO_ACTIVITY

    def test_negative_balance_adds_advice_and_renders_a_deficit(self) -> None:
        rendered = {
            i.sentence_id: i
            for i in render_insights(
                insights(balance_cents=-20_000_00), summary(balance_cents=-20_000_00)
            )
        }

        deficit = rendered[SentenceId.BALANCE_DEFICIT]
        assert deficit.message.replace(NBSP, " ") == "The period ended with a deficit of 20 000 ₸."
        assert deficit.advice == "Review your largest categories to see where you can cut back."

    def test_optional_topics_are_skipped_when_data_is_missing(self) -> None:
        topics = [
            i.topic
            for i in insights(top_expense_categories=[], expense_change_percentage=None).insights
        ]

        assert topics == [InsightTopic.OVERVIEW, InsightTopic.BALANCE]


def test_makes_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_args, **_kwargs):
        raise AssertionError("FakeAIProvider must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)

    assert draft("taxi 2500").amount_text == "2500"
    assert insights().insights
