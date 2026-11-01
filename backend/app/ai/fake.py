"""Deterministic, offline AI provider for local development and tests.

Same input → same output, no network, no API key. It uses simple keyword rules instead of a
model, and it follows the same contract as a real provider: amounts are returned as the text the
user wrote, and insights only quote backend-calculated facts.
"""

import re
from datetime import date, timedelta

from app.ai.facts import summary_facts
from app.ai.schemas import (
    CategoryOption,
    Insight,
    InsightsRequest,
    InsightsResult,
    TransactionDraft,
    TransactionDraftRequest,
)
from app.models import TransactionType

# Amount-looking token: "2500", "2 500", "2 500,50", "19.99".
_AMOUNT_PATTERN = r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_CURRENCY_PATTERN = r"₸|\b(?:kzt|tenge|тенге|тг)\b"
_AMOUNT = re.compile(_AMOUNT_PATTERN)
# An amount followed by a currency word wins over other numbers ("2 coffees 1500 tenge").
_AMOUNT_WITH_CURRENCY = re.compile(rf"({_AMOUNT_PATTERN})\s*(?:{_CURRENCY_PATTERN})", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CURRENCY_WORDS = re.compile(rf"({_CURRENCY_PATTERN})", re.IGNORECASE)

_INCOME_WORDS = (
    "salary",
    "paycheck",
    "got paid",
    "received",
    "income",
    "freelance",
    "bonus",
    "gift from",
    "зарплата",
    "зп",
    "получил",
)

# Keyword → default category name. Only used if that category is among the offered options.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Groceries": ("grocer", "magnum", "supermarket", "продукты"),
    "Restaurants & cafes": ("coffee", "cafe", "café", "restaurant", "lunch", "dinner", "кофе"),
    "Transport": ("taxi", "yandex", "uber", "bus", "metro", "fuel", "petrol", "такси"),
    "Housing & utilities": ("rent", "utilities", "electricity", "internet", "аренда"),
    "Health": ("pharmacy", "doctor", "dentist", "medicine", "аптека"),
    "Entertainment": ("cinema", "movie", "concert", "game", "кино"),
    "Shopping": ("kaspi", "clothes", "shoes", "wildberries", "ozon"),
    "Education": ("course", "book", "tuition", "school"),
    "Salary": ("salary", "paycheck", "зарплата", "зп"),
    "Freelance": ("freelance", "client", "project"),
    "Gifts": ("gift", "present", "подарок"),
}
_FALLBACK_CATEGORY = {
    TransactionType.EXPENSE: "Other expenses",
    TransactionType.INCOME: "Other income",
}


class FakeAIProvider:
    name = "fake"

    # --- Natural-language transaction entry ---------------------------------------

    def parse_transaction(self, request: TransactionDraftRequest) -> TransactionDraft:
        text = request.text
        lowered = text.lower()
        notes: list[str] = []

        occurred_on, date_text = self._find_date(text, lowered, request.today)
        amount_text = self._find_amount(text, date_text)
        if amount_text is None:
            notes.append("No amount found; please enter it.")

        type_ = (
            TransactionType.INCOME
            if any(word in lowered for word in _INCOME_WORDS)
            else TransactionType.EXPENSE
        )
        category = self._choose_category(lowered, type_, request.categories)
        if category is None:
            notes.append(f"No matching {type_} category; please choose one.")

        description = self._describe(text, amount_text, date_text) or (
            category.name if category else ""
        )
        return TransactionDraft(
            amount_text=amount_text,
            type=type_,
            category_id=category.id if category else None,
            description=description[:255] or "Transaction",
            occurred_on=occurred_on,
            notes=notes,
        )

    @staticmethod
    def _find_amount(text: str, date_text: str | None) -> str | None:
        """The amount exactly as written. Text only: it is never converted or computed here."""
        # Blank out an ISO date first, so "2026-10-20" is not read as an amount.
        searchable = text.replace(date_text, " " * len(date_text)) if date_text else text
        if match := _AMOUNT_WITH_CURRENCY.search(searchable):
            return match.group(1).strip()
        if match := _AMOUNT.search(searchable):
            return match.group(0).strip()
        return None

    @staticmethod
    def _find_date(text: str, lowered: str, today: date) -> tuple[date, str | None]:
        """Calendar logic only (no money): an ISO date, "yesterday", or today."""
        if match := _ISO_DATE.search(text):
            try:
                return date.fromisoformat(match.group(1)), match.group(1)
            except ValueError:
                pass
        if "yesterday" in lowered or "вчера" in lowered:
            return today - timedelta(days=1), None
        return today, None

    @staticmethod
    def _choose_category(
        lowered: str, type_: TransactionType, options: list[CategoryOption]
    ) -> CategoryOption | None:
        candidates = sorted((c for c in options if c.type == type_), key=lambda c: (c.name, c.id))
        by_name = {c.name.lower(): c for c in candidates}
        # 1. A category name written in the text ("groceries 5000").
        for category in candidates:
            if category.name.lower() in lowered:
                return category
        # 2. A known keyword for a default category ("taxi" → Transport).
        for name, keywords in _CATEGORY_KEYWORDS.items():
            if name.lower() in by_name and any(keyword in lowered for keyword in keywords):
                return by_name[name.lower()]
        # 3. The "Other …" category for this type, if it exists.
        return by_name.get(_FALLBACK_CATEGORY[type_].lower())

    @staticmethod
    def _describe(text: str, amount_text: str | None, date_text: str | None) -> str:
        """The user's words without the amount, currency and date."""
        description = text
        for part in (amount_text, date_text):
            if part:
                description = description.replace(part, " ", 1)
        description = _CURRENCY_WORDS.sub(" ", description)
        description = re.sub(
            r"\b(yesterday|today|вчера|сегодня)\b", " ", description, flags=re.IGNORECASE
        )
        description = re.sub(r"\s+", " ", description).strip(" ,.-")
        return description[:1].upper() + description[1:]

    # --- Spending insights ------------------------------------------------------------

    def generate_insights(self, request: InsightsRequest) -> InsightsResult:
        """Template sentences that quote backend facts verbatim; nothing is recalculated."""
        summary = request.summary
        facts = summary_facts(summary)

        if summary.transaction_count == 0:
            insights = [
                Insight(
                    title="No activity yet",
                    message=f"There are no transactions for {facts['period']}. "
                    "Add some to get insights.",
                )
            ]
            return InsightsResult(provider=self.name, insights=insights)

        insights = [
            Insight(
                title="Overview",
                message=f"In {facts['period']} you received {facts['income']} and spent "
                f"{facts['expenses']}. Your balance for the period is {facts['balance']}.",
            )
        ]
        # The backend's balance decides the tone; the fake provider never recomputes it.
        if summary.balance_cents < 0:
            insights.append(
                Insight(
                    title="Spending above income",
                    message="Your expenses were higher than your income in this period. "
                    "Review your largest categories for savings.",
                )
            )
        if "top_1_name" in facts:
            insights.append(
                Insight(
                    title="Largest expense category",
                    message=f"{facts['top_1_name']} was your largest expense: "
                    f"{facts['top_1_total']} ({facts['top_1_percentage']} of expenses).",
                )
            )
        if "expense_change" in facts:
            insights.append(
                Insight(
                    title="Compared with the previous period",
                    message=f"Your expenses changed by {facts['expense_change']} "
                    "compared with the previous period.",
                )
            )
        return InsightsResult(provider=self.name, insights=insights)
