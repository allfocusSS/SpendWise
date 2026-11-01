"""Financial calculations. Everything here is exact integer (cents) arithmetic done in Python/SQL.

The small pure functions at the top hold the math and are unit-tested directly; the query
functions below fetch sums from the database and hand them to those functions.
"""

from datetime import date
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


def month_starts(until: date, months: int) -> list[date]:
    """First day of each of the last `months` calendar months ending with `until`'s month.

    Oldest first, e.g. until=2026-03-15, months=3 → [2026-01-01, 2026-02-01, 2026-03-01].
    """
    if months < 1:
        raise ValueError("months must be at least 1")
    year, month = until.year, until.month
    starts = []
    for _ in range(months):
        starts.append(date(year, month, 1))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(starts))


def next_month_start(day: date) -> date:
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
    db: Session, user_id: int, date_from: date | None = None, date_to: date | None = None
) -> Summary:
    query = apply_filters(
        select(
            Transaction.type, func.sum(Transaction.amount_cents), func.count(Transaction.id)
        ).group_by(Transaction.type),
        TransactionFilters(user_id=user_id, date_from=date_from, date_to=date_to),
    )
    sums = {TransactionType.INCOME: 0, TransactionType.EXPENSE: 0}
    count = 0
    for type_, total, n in db.execute(query):
        # int(): PostgreSQL returns SUM(BIGINT) as Decimal; SQLite returns int.
        sums[TransactionType(type_)] = int(total)
        count += n

    return Summary(
        date_from=date_from,
        date_to=date_to,
        total_income_cents=sums[TransactionType.INCOME],
        total_expense_cents=sums[TransactionType.EXPENSE],
        balance_cents=calculate_balance(
            sums[TransactionType.INCOME], sums[TransactionType.EXPENSE]
        ),
        transaction_count=count,
    )


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
    period_start, period_end = month_list[0], next_month_start(month_list[-1])

    year_col = extract("year", Transaction.occurred_on)
    month_col = extract("month", Transaction.occurred_on)
    query = (
        select(year_col, month_col, Transaction.type, func.sum(Transaction.amount_cents))
        .where(
            Transaction.user_id == user_id,
            Transaction.occurred_on >= period_start,
            Transaction.occurred_on < period_end,
        )
        .group_by(year_col, month_col, Transaction.type)
    )
    totals = {
        (int(year), int(month), TransactionType(type_)): int(total)
        for year, month, type_, total in db.execute(query)
    }
    return MonthlyTrend(months=build_monthly_trend(month_list, totals))
