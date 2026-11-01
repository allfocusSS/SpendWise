from datetime import date

from pydantic import BaseModel

from app.models import TransactionType
from app.schemas.common import MoneyCents


class Summary(BaseModel):
    date_from: date | None
    date_to: date | None
    total_income_cents: MoneyCents
    total_expense_cents: MoneyCents
    # Can be negative when expenses exceed income.
    balance_cents: MoneyCents
    transaction_count: int


class CategoryBreakdownItem(BaseModel):
    category_id: int
    category_name: str
    color: str
    total_cents: MoneyCents
    transaction_count: int
    # Share of the period total, 0–100, rounded to 2 decimals (display only, not money).
    percentage: float


class CategoryBreakdown(BaseModel):
    type: TransactionType
    date_from: date | None
    date_to: date | None
    total_cents: MoneyCents
    items: list[CategoryBreakdownItem]


class MonthlyTrendItem(BaseModel):
    month: str  # "YYYY-MM"
    income_cents: MoneyCents
    expense_cents: MoneyCents
    # Can be negative when expenses exceed income.
    net_cents: MoneyCents


class MonthlyTrend(BaseModel):
    months: list[MonthlyTrendItem]
