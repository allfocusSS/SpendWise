"""Analytics over real HTTP, checked against a known ledger with hand-computed totals.

All amounts are tiyn. Expected values are written out, not recomputed, so the test checks the
backend's arithmetic and rounding rather than repeating it.
"""

import pytest

from integration.conftest import User

# (date, type, category, amount) for Alice; "Rent" is a custom category.
LEDGER = [
    ("2025-03-05", "income", "Salary", 50_000_000),
    ("2025-03-10", "expense", "Groceries", 4_000_000),
    ("2025-04-05", "income", "Salary", 52_000_000),
    ("2025-04-12", "income", "Freelance", 8_000_050),
    ("2025-04-15", "expense", "Groceries", 3_550_025),
    ("2025-04-20", "expense", "Transport", 1_200_000),
    ("2025-04-25", "expense", "Rent", 20_000_000),
    ("2025-05-05", "income", "Salary", 52_000_000),
]


@pytest.fixture
def alice_ledger(alice: User) -> User:
    alice.post("/api/categories", json={"name": "Rent", "type": "expense"})
    ids = alice.category_ids()
    for day, type_, category, amount in LEDGER:
        response = alice.post(
            "/api/transactions",
            json={
                "amount_cents": amount,
                "type": type_,
                "category_id": ids[category],
                "description": f"{category} {day}",
                "occurred_on": day,
            },
        )
        assert response.status_code == 201, response.text
    return alice


def test_all_time_summary(alice_ledger: User) -> None:
    assert alice_ledger.get("/api/analytics/summary").json() == {
        "date_from": None,
        "date_to": None,
        "total_income_cents": 162_000_050,
        "total_expense_cents": 28_750_025,
        "balance_cents": 133_250_025,
        "transaction_count": 8,
    }


def test_summary_for_one_month(alice_ledger: User) -> None:
    body = alice_ledger.get(
        "/api/analytics/summary", params={"date_from": "2025-04-01", "date_to": "2025-04-30"}
    ).json()

    assert (
        body["total_income_cents"],
        body["total_expense_cents"],
        body["balance_cents"],
        body["transaction_count"],
    ) == (60_000_050, 24_750_025, 35_250_025, 5)


def test_expense_breakdown(alice_ledger: User) -> None:
    body = alice_ledger.get("/api/analytics/by-category", params={"type": "expense"}).json()

    assert body["total_cents"] == 28_750_025
    assert [
        (i["category_name"], i["total_cents"], i["transaction_count"], i["percentage"])
        for i in body["items"]
    ] == [
        ("Rent", 20_000_000, 1, 69.57),
        ("Groceries", 7_550_025, 2, 26.26),
        ("Transport", 1_200_000, 1, 4.17),
    ]


def test_income_breakdown(alice_ledger: User) -> None:
    body = alice_ledger.get("/api/analytics/by-category", params={"type": "income"}).json()

    assert body["total_cents"] == 162_000_050
    assert [(i["category_name"], i["total_cents"], i["percentage"]) for i in body["items"]] == [
        ("Salary", 154_000_000, 95.06),
        ("Freelance", 8_000_050, 4.94),
    ]


def test_monthly_trend(alice_ledger: User) -> None:
    body = alice_ledger.get(
        "/api/analytics/monthly-trend", params={"months": 4, "until": "2025-05-31"}
    ).json()

    assert body["months"] == [
        {"month": "2025-02", "income_cents": 0, "expense_cents": 0, "net_cents": 0},
        {
            "month": "2025-03",
            "income_cents": 50_000_000,
            "expense_cents": 4_000_000,
            "net_cents": 46_000_000,
        },
        {
            "month": "2025-04",
            "income_cents": 60_000_050,
            "expense_cents": 24_750_025,
            "net_cents": 35_250_025,
        },
        {
            "month": "2025-05",
            "income_cents": 52_000_000,
            "expense_cents": 0,
            "net_cents": 52_000_000,
        },
    ]


def test_another_user_sees_none_of_it(alice_ledger: User, bob: User) -> None:
    summary = bob.get("/api/analytics/summary").json()
    assert (summary["total_income_cents"], summary["total_expense_cents"]) == (0, 0)
    assert summary["transaction_count"] == 0

    for type_ in ("income", "expense"):
        breakdown = bob.get("/api/analytics/by-category", params={"type": type_}).json()
        assert (breakdown["total_cents"], breakdown["items"]) == (0, [])

    trend = bob.get("/api/analytics/monthly-trend", params={"months": 4, "until": "2025-05-31"})
    assert all(m["income_cents"] == m["expense_cents"] == 0 for m in trend.json()["months"])


def test_each_user_gets_only_their_own_totals(alice_ledger: User, bob: User) -> None:
    ids = bob.category_ids()
    for category, type_, amount in [
        ("Salary", "income", 30_000_000),
        ("Health", "expense", 750_050),
    ]:
        bob.post(
            "/api/transactions",
            json={
                "amount_cents": amount,
                "type": type_,
                "category_id": ids[category],
                "description": "bob",
                "occurred_on": "2025-04-10",
            },
        )

    bob_summary = bob.get("/api/analytics/summary").json()
    assert (bob_summary["total_income_cents"], bob_summary["total_expense_cents"]) == (
        30_000_000,
        750_050,
    )
    bob_expenses = bob.get("/api/analytics/by-category", params={"type": "expense"}).json()
    assert [i["category_name"] for i in bob_expenses["items"]] == ["Health"]

    # Alice's figures are unchanged by Bob's activity.
    assert alice_ledger.get("/api/analytics/summary").json()["balance_cents"] == 133_250_025
