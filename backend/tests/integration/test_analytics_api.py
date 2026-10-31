"""Analytics endpoints computed from real rows in the database."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ledger(client: TestClient, category_ids) -> None:
    """A small, hand-checkable set of transactions (amounts in cents)."""
    rows = [
        # September 2026
        ("income", "Salary", 400_000_00, "2026-09-05"),
        ("expense", "Groceries", 60_000_00, "2026-09-10"),
        # October 2026
        ("income", "Salary", 450_000_00, "2026-10-05"),
        ("income", "Freelance", 50_000_50, "2026-10-12"),
        ("expense", "Groceries", 75_000_25, "2026-10-14"),
        ("expense", "Groceries", 24_999_75, "2026-10-20"),
        ("expense", "Transport", 50_000_00, "2026-10-21"),
    ]
    for type_, category, amount, day in rows:
        response = client.post(
            "/api/transactions",
            json={
                "amount_cents": amount,
                "type": type_,
                "category_id": category_ids[category],
                "description": f"{category} {day}",
                "occurred_on": day,
            },
        )
        assert response.status_code == 201, response.text


def test_summary_on_empty_database(client: TestClient) -> None:
    body = client.get("/api/analytics/summary").json()

    assert body["total_income_cents"] == 0
    assert body["total_expense_cents"] == 0
    assert body["balance_cents"] == 0
    assert body["transaction_count"] == 0


def test_all_time_summary(client: TestClient, ledger) -> None:
    body = client.get("/api/analytics/summary").json()

    assert body["total_income_cents"] == 900_000_50
    assert body["total_expense_cents"] == 210_000_00
    assert body["balance_cents"] == 690_000_50
    assert body["transaction_count"] == 7


def test_summary_for_date_range(client: TestClient, ledger) -> None:
    body = client.get(
        "/api/analytics/summary", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}
    ).json()

    assert body["total_income_cents"] == 500_000_50
    assert body["total_expense_cents"] == 150_000_00
    assert body["balance_cents"] == 350_000_50
    assert body["transaction_count"] == 5


def test_summary_rejects_inverted_range(client: TestClient) -> None:
    response = client.get(
        "/api/analytics/summary", params={"date_from": "2026-10-31", "date_to": "2026-10-01"}
    )

    assert response.status_code == 422


def test_expense_breakdown_by_category(client: TestClient, ledger) -> None:
    body = client.get(
        "/api/analytics/by-category",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
    ).json()

    assert body["type"] == "expense"
    assert body["total_cents"] == 150_000_00
    assert [
        (i["category_name"], i["total_cents"], i["transaction_count"], i["percentage"])
        for i in body["items"]
    ] == [
        ("Groceries", 100_000_00, 2, 66.67),
        ("Transport", 50_000_00, 1, 33.33),
    ]


def test_income_breakdown_by_category(client: TestClient, ledger) -> None:
    body = client.get("/api/analytics/by-category", params={"type": "income"}).json()

    assert [(i["category_name"], i["total_cents"]) for i in body["items"]] == [
        ("Salary", 850_000_00),
        ("Freelance", 50_000_50),
    ]


def test_breakdown_empty_period(client: TestClient, ledger) -> None:
    body = client.get(
        "/api/analytics/by-category", params={"date_from": "2020-01-01", "date_to": "2020-12-31"}
    ).json()

    assert body["total_cents"] == 0
    assert body["items"] == []


def test_monthly_trend(client: TestClient, ledger) -> None:
    body = client.get(
        "/api/analytics/monthly-trend", params={"months": 3, "until": "2026-10-31"}
    ).json()

    assert body["months"] == [
        {"month": "2026-08", "income_cents": 0, "expense_cents": 0, "net_cents": 0},
        {
            "month": "2026-09",
            "income_cents": 400_000_00,
            "expense_cents": 60_000_00,
            "net_cents": 340_000_00,
        },
        {
            "month": "2026-10",
            "income_cents": 500_000_50,
            "expense_cents": 150_000_00,
            "net_cents": 350_000_50,
        },
    ]


@pytest.mark.parametrize("months", [0, 25])
def test_monthly_trend_validates_months(client: TestClient, months: int) -> None:
    assert client.get("/api/analytics/monthly-trend", params={"months": months}).status_code == 422
