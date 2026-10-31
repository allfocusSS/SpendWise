"""Unit tests for the pure financial calculation helpers (no database)."""

from datetime import date

import pytest

from app.services.analytics import (
    build_monthly_trend,
    calculate_balance,
    calculate_percentage,
    month_starts,
    next_month_start,
)


class TestCalculateBalance:
    def test_income_minus_expenses(self) -> None:
        assert calculate_balance(500_000_00, 120_000_50) == 379_999_50

    def test_negative_when_overspending(self) -> None:
        assert calculate_balance(100_00, 250_00) == -150_00

    def test_zero_when_empty(self) -> None:
        assert calculate_balance(0, 0) == 0

    def test_large_amounts_stay_exact(self) -> None:
        # Values that would lose precision as floats (> 2**53) must stay exact.
        income = 9_007_199_254_740_993
        assert calculate_balance(income, 1) == 9_007_199_254_740_992


class TestCalculatePercentage:
    def test_simple_share(self) -> None:
        assert calculate_percentage(25_00, 100_00) == 25.0

    def test_rounds_half_up_to_two_decimals(self) -> None:
        # 1/3 = 33.333…% and 2/3 = 66.666…%
        assert calculate_percentage(1, 3) == 33.33
        assert calculate_percentage(2, 3) == 66.67
        # 1/32 = 3.125% exactly → half-up gives 3.13 (banker's rounding would give 3.12)
        assert calculate_percentage(1, 32) == 3.13

    def test_zero_total_returns_zero(self) -> None:
        assert calculate_percentage(0, 0) == 0.0

    def test_whole(self) -> None:
        assert calculate_percentage(42, 42) == 100.0


class TestMonthStarts:
    def test_returns_oldest_first(self) -> None:
        assert month_starts(date(2026, 3, 15), 3) == [
            date(2026, 1, 1),
            date(2026, 2, 1),
            date(2026, 3, 1),
        ]

    def test_crosses_year_boundary(self) -> None:
        assert month_starts(date(2026, 2, 1), 4) == [
            date(2025, 11, 1),
            date(2025, 12, 1),
            date(2026, 1, 1),
            date(2026, 2, 1),
        ]

    def test_single_month(self) -> None:
        assert month_starts(date(2026, 10, 31), 1) == [date(2026, 10, 1)]

    def test_rejects_zero_months(self) -> None:
        with pytest.raises(ValueError):
            month_starts(date(2026, 1, 1), 0)


def test_next_month_start_handles_december() -> None:
    assert next_month_start(date(2026, 12, 1)) == date(2027, 1, 1)
    assert next_month_start(date(2026, 1, 31)) == date(2026, 2, 1)


class TestBuildMonthlyTrend:
    def test_fills_missing_months_with_zero_and_computes_net(self) -> None:
        months = month_starts(date(2026, 3, 1), 3)
        totals = {
            (2026, 1, "income"): 300_000_00,
            (2026, 1, "expense"): 120_000_00,
            (2026, 3, "expense"): 50_000_00,
        }

        trend = build_monthly_trend(months, totals)

        assert [(t.month, t.income_cents, t.expense_cents, t.net_cents) for t in trend] == [
            ("2026-01", 300_000_00, 120_000_00, 180_000_00),
            ("2026-02", 0, 0, 0),
            ("2026-03", 0, 50_000_00, -50_000_00),
        ]
