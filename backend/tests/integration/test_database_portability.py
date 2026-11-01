"""Behaviour that differs between SQLite and PostgreSQL drivers, checked on whichever database runs.

Run on PostgreSQL with TEST_DATABASE_URL (see conftest.py); CI does both.
"""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.schemas.common import MAX_AMOUNT_CENTS


def add(client: TestClient, category_id: int, type_: str, amount: int, day: str) -> dict:
    response = client.post(
        "/api/transactions",
        json={
            "amount_cents": amount,
            "type": type_,
            "category_id": category_id,
            "description": "big",
            "occurred_on": day,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_large_totals_are_exact_json_integers(client: TestClient, category_ids) -> None:
    # PostgreSQL returns SUM(BIGINT) and EXTRACT() as numeric (Python Decimal), SQLite as int.
    # Totals far past 32-bit range must still come back as exact integers, never floats.
    for _ in range(3):
        add(client, category_ids["Salary"], "income", MAX_AMOUNT_CENTS, "2026-10-05")
    add(client, category_ids["Groceries"], "expense", MAX_AMOUNT_CENTS - 1, "2026-10-06")

    summary = client.get("/api/analytics/summary").json()
    assert summary["total_income_cents"] == 3 * MAX_AMOUNT_CENTS
    assert summary["balance_cents"] == 2 * MAX_AMOUNT_CENTS + 1
    assert all(type(summary[key]) is int for key in ("total_income_cents", "balance_cents"))

    breakdown = client.get("/api/analytics/by-category", params={"type": "income"}).json()
    assert breakdown["total_cents"] == 3 * MAX_AMOUNT_CENTS
    assert type(breakdown["items"][0]["total_cents"]) is int

    trend = client.get(
        "/api/analytics/monthly-trend", params={"months": 1, "until": "2026-10-31"}
    ).json()
    assert trend["months"] == [
        {
            "month": "2026-10",
            "income_cents": 3 * MAX_AMOUNT_CENTS,
            "expense_cents": MAX_AMOUNT_CENTS - 1,
            "net_cents": 2 * MAX_AMOUNT_CENTS + 1,
        }
    ]


def test_timestamps_round_trip_as_aware_utc(client: TestClient, db: Session, category_ids) -> None:
    created = add(client, category_ids["Groceries"], "expense", 100, "2026-10-06")

    stored = db.scalars(select(Transaction).where(Transaction.id == created["id"])).one()
    assert stored.created_at.utcoffset() is not None
    assert stored.created_at.utcoffset().total_seconds() == 0
    assert stored.occurred_on == date(2026, 10, 6)
    assert created["created_at"].endswith(("Z", "+00:00"))


def test_ids_are_generated_by_the_database(client: TestClient, category_ids) -> None:
    first = add(client, category_ids["Groceries"], "expense", 100, "2026-10-06")
    second = add(client, category_ids["Groceries"], "expense", 100, "2026-10-06")
    assert second["id"] > first["id"]
