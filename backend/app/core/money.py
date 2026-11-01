"""Display formatting for money. Formatting only: no financial arithmetic happens here.

Amounts are integer tiyn (1 KZT = 100 tiyn). The output matches the frontend's formatKzt:
250000 → "2 500 ₸", 250050 → "2 500,50 ₸", -123455 → "-1 234,55 ₸".
"""

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


def format_percentage(value: float) -> str:
    """Format a backend-calculated percentage: 66.67 → "66.67%", 100.0 → "100%"."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"
