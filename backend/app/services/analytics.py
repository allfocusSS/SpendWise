"""Financial calculations. Everything here is exact integer (cents) arithmetic done in Python/SQL.

The small pure functions at the top hold the math and are unit-tested directly; the query
functions below fetch sums from the database and hand them to those functions.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.models import Category, Transaction, TransactionType
from app.schemas.analytics import (
    CategoryBreakdown,
    CategoryBreakdownItem,
    MonthlyTrend,
    MonthlyTrendItem,
    Summary,
)
from app.services.transactions import TransactionFilters, apply_filters

MAX_MONTHS = 24
TRANSACTION_YEAR = extract("year", Transaction.occurred_on)
TRANSACTION_MONTH = extract("month", Transaction.occurred_on)

# ---------------------------------------------------------------------------
# Pure calculation helpers
# ---------------------------------------------------------------------------


def calculate_balance(income_cents: int, expense_cents: int) -> int:
    """Balance = income − expenses. Negative means overspending."""
    return income_cents - expense_cents


def calculate_percentage(part_cents: int, total_cents: int) -> float:
    """Share of `part` in `total` as a percentage rounded half-up to 2 decimals.

    Computed with Decimal so the rounding is exact; returned as float for JSON/charts.
    """
    if total_cents <= 0:
        return 0.0
    share = Decimal(part_cents) * 100 / Decimal(total_cents)
    return float(share.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _month_index(day: date) -> int:
    return (day.year - 1) * 12 + day.month - 1


def month_starts(until: date, months: int) -> list[date]:
    """First day of each of the last `months` calendar months ending with `until`'s month.

    Oldest first, e.g. until=2026-03-15, months=3 → [2026-01-01, 2026-02-01, 2026-03-01].
    """
    if months < 1:
        raise ValueError("months must be at least 1")
    end = _month_index(until)
    return [
        date(index // 12 + 1, index % 12 + 1, 1)
        for index in range(max(0, end - months + 1), end + 1)
    ]


def next_month_start(day: date) -> date | None:
    if day.year == date.max.year and day.month == 12:
        return None
    return date(day.year + 1, 1, 1) if day.month == 12 else date(day.year, day.month + 1, 1)


def build_monthly_trend(
    month_list: list[date], totals: dict[tuple[int, int, str], int]
) -> list[MonthlyTrendItem]:
    """Turn {(year, month, type): cents} into one row per month, filling gaps with zero."""
    items = []
    for start in month_list:
        income = totals.get((start.year, start.month, TransactionType.INCOME), 0)
        expense = totals.get((start.year, start.month, TransactionType.EXPENSE), 0)
        items.append(
            MonthlyTrendItem(
                month=f"{start.year:04d}-{start.month:02d}",
                income_cents=income,
                expense_cents=expense,
                net_cents=calculate_balance(income, expense),
            )
        )
    return items


# ---------------------------------------------------------------------------
# Database-backed analytics
# ---------------------------------------------------------------------------


def get_summary(
    db: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    include_monthly: bool = False,
) -> Summary:
    grouped = select(
        Transaction.type, func.sum(Transaction.amount_cents), func.count(Transaction.id)
    ).group_by(Transaction.type)
    # A wide closed range can never return buckets. Keep the normal totals-only query for it.
    group_by_month = include_monthly and (
        date_from is None
        or date_to is None
        or _month_index(date_to) - _month_index(date_from) < MAX_MONTHS
    )
    if group_by_month:
        grouped = grouped.add_columns(TRANSACTION_YEAR, TRANSACTION_MONTH).group_by(
            TRANSACTION_YEAR, TRANSACTION_MONTH
        )
    query = apply_filters(
        grouped,
        TransactionFilters(user_id=user_id, date_from=date_from, date_to=date_to),
    )
    sums = {TransactionType.INCOME: 0, TransactionType.EXPENSE: 0}
    count = 0
    monthly_totals: dict[tuple[int, int, str], int] = {}
    for type_, total, n, *bucket in db.execute(query):
        # int(): PostgreSQL returns SUM(BIGINT) as Decimal; SQLite returns int.
        kind, amount = TransactionType(type_), int(total)
        sums[kind] += amount
        count += n
        if bucket:
            year, month = bucket
            monthly_totals[int(year), int(month), kind] = amount

    summary = Summary(
        date_from=date_from,
        date_to=date_to,
        total_income_cents=sums[TransactionType.INCOME],
        total_expense_cents=sums[TransactionType.EXPENSE],
        balance_cents=calculate_balance(
            sums[TransactionType.INCOME], sums[TransactionType.EXPENSE]
        ),
        transaction_count=count,
    )
    if include_monthly:
        summary.monthly_breakdown = (
            _summary_months(monthly_totals, date_from, date_to) if group_by_month else None
        )
    return summary


def _summary_months(
    totals: dict[tuple[int, int, str], int], date_from: date | None, date_to: date | None
) -> list[MonthlyTrendItem] | None:
    if not totals and (date_from is None or date_to is None):
        return []

    first = date_from or date(*min(totals)[:2], 1)
    last = date_to or date(*max(totals)[:2], 1)
    months = _month_index(last) - _month_index(first) + 1
    if months > MAX_MONTHS:
        return None
    return build_monthly_trend(month_starts(last, months), totals)


def get_category_breakdown(
    db: Session,
    user_id: int,
    type_: TransactionType = TransactionType.EXPENSE,
    date_from: date | None = None,
    date_to: date | None = None,
) -> CategoryBreakdown:
    total_col = func.sum(Transaction.amount_cents).label("total")
    query = apply_filters(
        select(Category.id, Category.name, Category.color, total_col, func.count(Transaction.id))
        .join(Transaction.category)
        .where(Category.user_id == user_id)
        .group_by(Category.id, Category.name, Category.color)
        .order_by(total_col.desc(), Category.name),
        TransactionFilters(user_id=user_id, date_from=date_from, date_to=date_to, type=type_),
    )
    rows = [(cid, name, color, int(total), n) for cid, name, color, total, n in db.execute(query)]
    grand_total = sum(row[3] for row in rows)

    return CategoryBreakdown(
        type=type_,
        date_from=date_from,
        date_to=date_to,
        total_cents=grand_total,
        items=[
            CategoryBreakdownItem(
                category_id=cid,
                category_name=name,
                color=color,
                total_cents=total,
                transaction_count=n,
                percentage=calculate_percentage(total, grand_total),
            )
            for cid, name, color, total, n in rows
        ],
    )


def get_monthly_trend(
    db: Session, user_id: int, months: int = 6, until: date | None = None
) -> MonthlyTrend:
    until = until or date.today()
    month_list = month_starts(until, months)
    following_month = next_month_start(until)
    period_end = following_month - timedelta(days=1) if following_month else date.max

    query = apply_filters(
        select(
            TRANSACTION_YEAR,
            TRANSACTION_MONTH,
            Transaction.type,
            func.sum(Transaction.amount_cents),
        ).group_by(TRANSACTION_YEAR, TRANSACTION_MONTH, Transaction.type),
        TransactionFilters(user_id=user_id, date_from=month_list[0], date_to=period_end),
    )
    totals = {
        (int(year), int(month), TransactionType(type_)): int(total)
        for year, month, type_, total in db.execute(query)
    }
    return MonthlyTrend(months=build_monthly_trend(month_list, totals))
