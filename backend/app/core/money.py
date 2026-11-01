"""Display formatting and input checks for money. No financial arithmetic happens here.

Amounts are integer tiyn (1 KZT = 100 tiyn). The output matches the frontend's formatKzt:
250000 → "2 500 ₸", 250050 → "2 500,50 ₸", -123455 → "-1 234,55 ₸".
"""

import re
from decimal import ROUND_HALF_UP, Decimal

# Non-breaking space: keeps "2 500 ₸" together, like the frontend's Intl output.
NBSP = "\u00a0"


def format_kzt(tiyn: int) -> str:
    """Format integer tiyn as tenge using string operations only."""
    if isinstance(tiyn, bool) or not isinstance(tiyn, int):
        raise TypeError(f"format_kzt expects an integer number of tiyn, got {tiyn!r}")

    sign = "-" if tiyn < 0 else ""
    digits = str(tiyn).lstrip("-").rjust(3, "0")
    whole, fraction = digits[:-2], digits[-2:]
    grouped = f"{int(whole):,}".replace(",", NBSP)
    amount = grouped if fraction == "00" else f"{grouped},{fraction}"
    return f"{sign}{amount}{NBSP}₸"


def rounded_percentage(value: float) -> Decimal:
    """A percentage rounded half-up to 2 decimals, with -0 turned into 0.

    Decisions such as "increase" vs "decrease" use this value, so a change of 0.004% is "no
    change" rather than "a 0% increase".
    """
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return rounded if rounded != 0 else Decimal("0.00")


def format_percentage(value: float) -> str:
    """66.67 → "66.67%", 100.0 → "100%", -0.0 → "0%", 0.004 → "0%"."""
    text = format(rounded_percentage(value), "f").rstrip("0").rstrip(".")
    return f"{text}%"


# --- Amounts typed by users -------------------------------------------------------------

# Accepted between thousands groups: space, no-break space, narrow no-break space (U+202F),
# thin space (U+2009) and figure space (U+2007). Exactly one, between exact 3-digit groups.
GROUP_SEPARATORS = frozenset(" \u00a0\u202f\u2009\u2007")

# ASCII digits only. "\s+" (any whitespace run) is matched here so that unclear separators such
# as tabs or double spaces are reported, not silently split into two numbers.
_AMOUNT_SHAPE = re.compile(r"([0-9]+(?:\s+[0-9]+)*)(?:([.,])([0-9]+))?")


def amount_text_problem(text: str) -> str | None:
    """Why `text` is not an unambiguous amount, or None if it is.

    Unambiguous: ASCII digits, optionally grouped into thousands by one of GROUP_SEPARATORS
    (first group 1–3 digits, then exactly 3), optionally followed by "," or "." and 1–2 decimals.
    Comma/dot thousands ("450,000", "1,234,567") and 3+ decimals ("12.500") are ambiguous: they
    could mean 450 000 or 450.00, so they are rejected rather than reinterpreted.
    """
    if any(char.isdigit() and not "0" <= char <= "9" for char in text):
        return "uses non-ASCII digits; please use 0-9"
    match = _AMOUNT_SHAPE.fullmatch(text)
    if match is None:
        return "is ambiguous; use spaces for thousands and at most 2 decimals"
    whole, fraction = match.group(1), match.group(3)
    separators = re.findall(r"\s+", whole)
    if any(len(sep) != 1 or sep not in GROUP_SEPARATORS for sep in separators):
        return "has an unclear separator between digits; use a single space between thousands"
    groups = re.split(r"\s", whole)
    if len(groups) > 1 and (len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:])):
        return "has malformed digit grouping; thousands groups must have exactly 3 digits"
    if fraction is not None and len(fraction) > 2:
        return "is ambiguous; use spaces for thousands and at most 2 decimals"
    return None


def is_unambiguous_amount(text: str) -> bool:
    return amount_text_problem(text) is None
