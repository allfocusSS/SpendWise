from datetime import date

from pydantic import BaseModel

from app.models import TransactionType


class Summary(BaseModel):
    date_from: date | None
    date_to: date | None
    total_income_cents: int
    total_expense_cents: int
    # Can be negative when expenses exceed income.
    balance_cents: int
    transaction_count: int


class CategoryBreakdownItem(BaseModel):
    category_id: int
    category_name: str
    color: str
    total_cents: int
    transaction_count: int
    # Share of the period total, 0–100, rounded to 2 decimals (display only, not money).
    percentage: float


class CategoryBreakdown(BaseModel):
    type: TransactionType
    date_from: date | None
    date_to: date | None
    total_cents: int
    items: list[CategoryBreakdownItem]


class MonthlyTrendItem(BaseModel):
    month: str  # "YYYY-MM"
    income_cents: int
    expense_cents: int
    net_cents: int


class MonthlyTrend(BaseModel):
    months: list[MonthlyTrendItem]
