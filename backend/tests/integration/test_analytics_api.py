"""Analytics endpoints computed from real rows in the database."""

import pytest
from fastapi.testclient import TestClient


def make_transaction(
    client: TestClient, category_id: int, type_: str, amount: int, day: str
) -> None:
    response = client.post(
        "/api/transactions",
        json={
            "amount_cents": amount,
            "type": type_,
            "category_id": category_id,
            "description": f"{type_} on {day}",
            "occurred_on": day,
        },
    )
    assert response.status_code == 201, response.text


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
        make_transaction(client, category_ids[category], type_, amount, day)


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
    assert "monthly_breakdown" not in body


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (
            {"date_from": "2026-09-10", "date_to": "2026-10-14"},
            [("2026-09", 0, 60_000_00, -60_000_00), ("2026-10", 500_000_50, 75_000_25, 425_000_25)],
        ),
        (
            {"date_from": "2026-09-10"},
            [
                ("2026-09", 0, 60_000_00, -60_000_00),
                ("2026-10", 500_000_50, 150_000_00, 350_000_50),
            ],
        ),
        (
            {"date_to": "2026-10-14"},
            [
                ("2026-09", 400_000_00, 60_000_00, 340_000_00),
                ("2026-10", 500_000_50, 75_000_25, 425_000_25),
            ],
        ),
        (
            {"date_from": "2026-10-14", "date_to": "2026-10-14"},
            [("2026-10", 0, 75_000_25, -75_000_25)],
        ),
    ],
)
def test_monthly_breakdown_matches_exact_summary(
    client: TestClient, ledger, filters: dict[str, str], expected: list[tuple[str, int, int, int]]
) -> None:
    response = client.get("/api/analytics/summary", params={**filters, "include_monthly": True})
    assert response.status_code == 200, response.text
    body = response.json()
    rows = body.pop("monthly_breakdown")
    assert body == client.get("/api/analytics/summary", params=filters).json()
    assert [
        (r["month"], r["income_cents"], r["expense_cents"], r["net_cents"]) for r in rows
    ] == expected
    for key, total in (
        ("income_cents", "total_income_cents"),
        ("expense_cents", "total_expense_cents"),
        ("net_cents", "balance_cents"),
    ):
        assert sum(r[key] for r in rows) == body[total]


@pytest.mark.parametrize(
    ("filters", "expected_months"),
    [
        ({"date_from": "2024-12-31", "date_to": "2025-02-01"}, ["2024-12", "2025-01", "2025-02"]),
        ({"date_from": "2025-01-31", "date_to": "2026-12-01"}, 24),
        ({"date_from": "2024-12-31", "date_to": "2026-12-01"}, None),
        ({"date_from": "0001-01-01", "date_to": "9999-12-31"}, None),
        ({"date_from": "2026-01-01"}, []),
        ({}, []),
    ],
)
def test_monthly_breakdown_empty_and_wide_ranges(
    client: TestClient, filters, expected_months
) -> None:
    response = client.get("/api/analytics/summary", params={**filters, "include_monthly": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["balance_cents"] == 0
    rows = body["monthly_breakdown"]
    if expected_months is None:
        assert rows is None
    elif isinstance(expected_months, int):
        assert len(rows) == expected_months
        assert (rows[0]["month"], rows[-1]["month"]) == ("2025-01", "2026-12")
    else:
        assert rows == [
            {"month": month, "income_cents": 0, "expense_cents": 0, "net_cents": 0}
            for month in expected_months
        ]


def test_monthly_breakdown_wide_open_range_keeps_totals(client: TestClient, ledger) -> None:
    response = client.get(
        "/api/analytics/summary", params={"date_from": "2020-01-01", "include_monthly": True}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["monthly_breakdown"] is None
    assert body["balance_cents"] == 690_000_50


@pytest.mark.parametrize("include_monthly", [None, False, True])
def test_summary_rejects_inverted_range(client: TestClient, include_monthly: bool | None) -> None:
    filters: dict[str, str | bool] = {"date_from": "2026-10-31", "date_to": "2026-10-01"}
    if include_monthly is not None:
        filters["include_monthly"] = include_monthly
    response = client.get("/api/analytics/summary", params=filters)

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


@pytest.mark.parametrize(
    ("until", "booked", "expected_months"),
    [
        ("0001-01-01", "0001-01-01", ["0001-01"]),
        ("9999-12-01", "9999-12-31", ["9999-10", "9999-11", "9999-12"]),
        ("2028-02-01", "2028-02-29", ["2027-12", "2028-01", "2028-02"]),
    ],
)
def test_monthly_trend_includes_calendar_boundaries(
    client: TestClient, category_ids, until: str, booked: str, expected_months: list[str]
) -> None:
    make_transaction(client, category_ids["Salary"], "income", 12345, booked)
    response = client.get("/api/analytics/monthly-trend", params={"months": 3, "until": until})
    assert response.status_code == 200, response.text
    assert response.json()["months"] == [
        {
            "month": month,
            "income_cents": 12345 if month == booked[:7] else 0,
            "expense_cents": 0,
            "net_cents": 12345 if month == booked[:7] else 0,
        }
        for month in expected_months
    ]


@pytest.mark.parametrize("until", ["0000-12-31", "10000-01-01", "2027-02-29"])
def test_monthly_trend_rejects_unsupported_date(client: TestClient, until: str) -> None:
    response = client.get("/api/analytics/monthly-trend", params={"until": until})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "until"]
