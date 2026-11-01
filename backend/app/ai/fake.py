"""Deterministic, offline AI provider for local development and tests.

Same input → same output, no network, no API key. It uses simple keyword rules instead of a
model, and it follows the same contract as a real provider: amounts are returned as the text the
user wrote, and insights are topic selections whose sentences the backend renders (app/ai/facts.py).
"""

import re
import unicodedata
from datetime import date, timedelta

from app.ai.schemas import (
    CategoryOption,
    InsightSelection,
    InsightsRequest,
    InsightsResult,
    InsightTopic,
    TransactionDraft,
    TransactionDraftRequest,
)
from app.ai.text_checks import PERCENT_MARKERS
from app.core.money import amount_text_problem
from app.models import TransactionType

# A number is always taken WHOLE: ASCII digit runs joined across horizontal whitespace (any kind,
# including tabs and U+202F) plus every ",digits"/".digits" part. "2\u202f500", "12 34" and
# "450,000" each become one token that is then accepted or rejected as a whole, never cut down.
_NUMBER_TOKEN = re.compile(r"(?<![0-9.,])[0-9]+(?:[^\S\r\n]+[0-9]+)*(?:[.,][0-9]+)*")
_CURRENCY_NAMES = r"kzt|tenge|теңге|тенге|тңг|тг|tg"
# A currency word right after ("1500 tenge", "5000tg") or right before ("₸1500", "KZT 900").
_CURRENCY_AFTER = re.compile(rf"[^\S\r\n]*(?:₸|(?:{_CURRENCY_NAMES})\b)", re.IGNORECASE)
_CURRENCY_BEFORE = re.compile(rf"(?:₸|\b(?:{_CURRENCY_NAMES}))[^\S\r\n]*$", re.IGNORECASE)
_CURRENCY_WORDS = re.compile(rf"₸|\b(?:{_CURRENCY_NAMES})\b", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Things that change what a number means. The parser never converts them; it leaves the amount
# empty with a note. Other currencies: any currency symbol except ₸ (Unicode category Sc) or one
# of these words, also when glued to digits ("usd50"), but not inside other words ("рубашка").
_FOREIGN_CURRENCY_WORDS = re.compile(
    r"(?<![^\W\d_])(?:usd|eur|gbp|rub|cny|dollars?|euros?|руб|рубл\w*|доллар\w*|евро|бакс\w*)"
    r"(?![^\W\d_])",
    re.IGNORECASE,
)
# A calculation or range between two numbers ("3000/2", "1500-2000", "2 x 1500", or any symbol
# standing alone between them: "1500 – 2000"), a multiplication sign attached to a number ("x2",
# "2x"), or a percentage ("10%", "10 процентов").
_CALCULATION = re.compile(
    r"[0-9]+[^\S\r\n]*[-+*/×÷xх][^\S\r\n]*[0-9]+"
    r"|[0-9]+(?:[^\S\r\n]+[^\w\s.,()]+[^\S\r\n]*|[^\S\r\n]*[^\w\s.,()]+[^\S\r\n]+)[0-9]+"
    r"|(?<![^\W\d_])[*×xх][0-9]+|[0-9]+[*×xх](?![^\W\d_])"
    rf"|[0-9]+[^\S\r\n]*(?:[％﹪{''.join(PERCENT_MARKERS)}]|percent|процент|пайыз)",
    re.IGNORECASE,
)
# A multiplier written after the amount ("5 млн", "300 тыс.", "2.5 thousand"). Single letters
# count only when attached ("1.5k", "2к"), except Latin "k": a lone Cyrillic "к" is also the
# Russian word "to".
_MULTIPLIER_AFTER = re.compile(
    r"[^\S\r\n]*(?:k|тыс\w*|млн\w*|млрд\w*|миллион\w*|миллиард\w*|мың|mln|mn|bn|thousands?"
    r"|millions?|billions?|grand)\b",
    re.IGNORECASE,
)
# The only characters that may touch an amount without a space in between. Anything else in the
# same whitespace-separated word ("1'500", "1500–2000", "usd50", "iphone15", invisible characters)
# means the amount cannot be proven to stand alone, so it is not returned.
_ALLOWED_PREFIX = re.compile(rf"[(\[«\"“'‘]*(?:₸|{_CURRENCY_NAMES})?-?", re.IGNORECASE)
_ALLOWED_SUFFIX = re.compile(rf"(?:₸|{_CURRENCY_NAMES})?[)\]»\"”'’.,!?;:]*", re.IGNORECASE)

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


def _show_invisible(text: str) -> str:
    """Make invisible characters visible in notes: "1\u200b500" → "1<U+200B>500"."""
    return "".join(
        f"<U+{ord(c):04X}>" if unicodedata.category(c) in ("Cf", "Cc") else c for c in text
    )


class FakeAIProvider:
    name = "fake"

    # --- Natural-language transaction entry ---------------------------------------

    def parse_transaction(self, request: TransactionDraftRequest) -> TransactionDraft:
        text = request.text
        lowered = text.lower()
        notes: list[str] = []

        occurred_on, date_span = self._find_date(text, lowered, request.today)
        amount_span, amount_note = self._find_amount(text, date_span)
        amount_text = text[amount_span[0] : amount_span[1]] if amount_span else None
        if amount_note:
            notes.append(amount_note)

        type_ = (
            TransactionType.INCOME
            if any(word in lowered for word in _INCOME_WORDS)
            else TransactionType.EXPENSE
        )
        category = self._choose_category(lowered, type_, request.categories)
        if category is None:
            notes.append(f"No matching {type_} category; please choose one.")

        description = self._describe(text, amount_span, date_span) or (
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
    def _find_amount(
        text: str, date_span: tuple[int, int] | None
    ) -> tuple[tuple[int, int] | None, str | None]:
        """(span of the amount exactly as written, note). Never converts or computes anything.

        Nothing is guessed: if the amount is ambiguous, malformed, written with non-ASCII digits or
        numerals, in another currency, part of a calculation, range or percentage, followed by a
        multiplier ("1.5k", "5 млн"), or several numbers could be the amount, the span is None and
        the note says why.
        """
        if numeral := next((c for c in text if c.isnumeric() and not "0" <= c <= "9"), None):
            return None, (
                f"Only the digits 0-9 are supported (found '{numeral}'); "
                "please enter the amount with them."
            )
        currency = next((c for c in text if c != "₸" and unicodedata.category(c) == "Sc"), None)
        if currency or (match := _FOREIGN_CURRENCY_WORDS.search(text)):
            found = currency or match.group(0)
            return None, f"Only tenge is supported (found '{found}'); please enter the amount."
        # Hide an ISO date (with a non-digit, non-space filler) so it is not read as an amount.
        searchable = text
        if date_span:
            start, end = date_span
            searchable = text[:start] + "#" * (end - start) + text[end:]
        if match := _CALCULATION.search(searchable):
            return None, (
                f"The text contains a calculation, range or percentage ('{match.group(0)}'); "
                "please enter the final amount."
            )

        tokens = list(_NUMBER_TOKEN.finditer(searchable))
        if not tokens:
            return None, "No amount found; please enter it."
        near_currency = [
            t
            for t in tokens
            if _CURRENCY_AFTER.match(searchable, t.end())
            or _CURRENCY_BEFORE.search(searchable, 0, t.start())
        ]
        candidates = near_currency or tokens
        if len(candidates) > 1:
            listed = ", ".join(f"'{t.group(0)}'" for t in candidates)
            return None, f"Several possible amounts ({listed}); please enter the amount."

        chosen = candidates[0]
        if problem := amount_text_problem(chosen.group(0)):
            return None, f"Amount '{chosen.group(0)}' {problem}."
        prefix = re.search(r"\S*\Z", searchable[: chosen.start()]).group(0)
        suffix = re.match(r"\S*", searchable[chosen.end() :]).group(0)
        multiplier = _MULTIPLIER_AFTER.match(searchable, chosen.end())
        suffix_ok = _ALLOWED_SUFFIX.fullmatch(suffix)
        if multiplier or (not suffix_ok and suffix[:1].isalpha()):
            unit = multiplier.group(0).split()[0] if multiplier else re.match(r"\w+", suffix)[0]
            return None, (
                f"Amount '{chosen.group(0)}' is followed by '{unit}'; multipliers are not "
                "converted, please enter the full amount in digits."
            )
        if not suffix_ok or not _ALLOWED_PREFIX.fullmatch(prefix):
            return None, (
                f"Amount '{chosen.group(0)}' is written together with other characters "
                f"('{_show_invisible(prefix + chosen.group(0) + suffix)}'); please enter the "
                "amount using only the digits 0-9 and spaces."
            )
        return chosen.span(), None

    @staticmethod
    def _find_date(text: str, lowered: str, today: date) -> tuple[date, tuple[int, int] | None]:
        """Calendar logic only (no money): an ISO date (with its span), "yesterday", or today."""
        if match := _ISO_DATE.search(text):
            try:
                return date.fromisoformat(match.group(1)), match.span(1)
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
    def _describe(
        text: str, amount_span: tuple[int, int] | None, date_span: tuple[int, int] | None
    ) -> str:
        """The user's words without the amount, currency and date (removed by position)."""
        description = text
        for start, end in sorted((s for s in (amount_span, date_span) if s), reverse=True):
            description = description[:start] + " " + description[end:]
        description = _CURRENCY_WORDS.sub(" ", description)
        description = re.sub(
            r"\b(yesterday|today|вчера|сегодня)\b", " ", description, flags=re.IGNORECASE
        )
        description = re.sub(r"\s+", " ", description).strip(" ,.-")
        return description[:1].upper() + description[1:]

    # --- Spending insights ------------------------------------------------------------

    def generate_insights(self, request: InsightsRequest) -> InsightsResult:
        """Topic selections only. The backend picks and renders every sentence with a figure.

        The provider reads the summary to decide WHICH topics and advice fit (e.g. advice for a
        negative balance), but never writes, recomputes or reformats a value.
        """
        summary = request.summary
        if summary.transaction_count == 0:
            return InsightsResult(provider=self.name, insights=[])

        balance_advice = (
            "Review your largest categories to see where you can cut back."
            if summary.balance_cents < 0
            else None
        )
        insights = [
            InsightSelection(topic=InsightTopic.OVERVIEW),
            InsightSelection(topic=InsightTopic.BALANCE, advice=balance_advice),
        ]
        if summary.top_expense_categories:
            insights.append(
                InsightSelection(
                    topic=InsightTopic.TOP_CATEGORY,
                    advice="A monthly limit for this category can help you plan ahead.",
                )
            )
        if summary.expense_change_percentage is not None:
            insights.append(InsightSelection(topic=InsightTopic.EXPENSE_CHANGE))
        return InsightsResult(provider=self.name, insights=insights)
