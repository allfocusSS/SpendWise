"""Transactions over real HTTP: create, list and filter, update, delete, cross-user access."""

import pytest

from integration.conftest import User


def payload(category_id: int, amount: int, type_: str, day: str, description: str = "x") -> dict:
    return {
        "amount_cents": amount,
        "type": type_,
        "category_id": category_id,
        "description": description,
        "occurred_on": day,
    }


def create(user: User, *args, **kwargs) -> dict:
    response = user.post("/api/transactions", json=payload(*args, **kwargs))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def ledger(alice: User) -> dict[str, dict]:
    """Three of Alice's transactions in October 2026."""
    ids = alice.category_ids()
    return {
        "salary": create(alice, ids["Salary"], 450_000_00, "income", "2026-10-05", "Salary"),
        "groceries": create(alice, ids["Groceries"], 12_345_67, "expense", "2026-10-10", "Food"),
        "bus": create(alice, ids["Transport"], 1_500_00, "expense", "2026-10-21", "Bus"),
    }


def test_create_income_and_expense(alice: User, ledger) -> None:
    salary, groceries = ledger["salary"], ledger["groceries"]

    assert (salary["type"], salary["amount_cents"], salary["category"]["name"]) == (
        "income",
        450_000_00,
        "Salary",
    )
    assert (groceries["type"], groceries["amount_cents"], groceries["category"]["name"]) == (
        "expense",
        12_345_67,
        "Groceries",
    )
    assert groceries["source"] == "manual"
    assert groceries["created_at"].endswith(("Z", "+00:00"))
    assert alice.get(f"/api/transactions/{groceries['id']}").json() == groceries


def test_list_is_newest_first(alice: User, ledger) -> None:
    body = alice.get("/api/transactions").json()

    assert body["total"] == 3
    assert [t["id"] for t in body["items"]] == [
        ledger["bus"]["id"],
        ledger["groceries"]["id"],
        ledger["salary"]["id"],
    ]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"type": "expense"}, {"groceries", "bus"}),
        ({"type": "income"}, {"salary"}),
        ({"date_from": "2026-10-06", "date_to": "2026-10-20"}, {"groceries"}),
        ({"date_from": "2026-10-21"}, {"bus"}),
        ({"date_to": "2026-10-05"}, {"salary"}),
    ],
)
def test_filters(alice: User, ledger, params: dict, expected: set[str]) -> None:
    body = alice.get("/api/transactions", params=params).json()

    names = {name for name, tx in ledger.items() if tx["id"] in {t["id"] for t in body["items"]}}
    assert names == expected
    assert body["total"] == len(expected)


def test_filter_by_category_and_paginate(alice: User, ledger) -> None:
    transport = alice.category_ids()["Transport"]
    assert [
        t["id"]
        for t in alice.get("/api/transactions", params={"category_id": transport}).json()["items"]
    ] == [ledger["bus"]["id"]]

    first = alice.get("/api/transactions", params={"limit": 2, "offset": 0}).json()
    second = alice.get("/api/transactions", params={"limit": 2, "offset": 2}).json()
    assert (first["total"], len(first["items"]), len(second["items"])) == (3, 2, 1)


def test_invalid_input_is_rejected(alice: User) -> None:
    groceries = alice.category_ids()["Groceries"]

    assert (
        alice.post(
            "/api/transactions", json=payload(groceries, 10.5, "expense", "2026-10-01")
        ).status_code
        == 422
    )
    assert (
        alice.post(
            "/api/transactions", json=payload(groceries, 0, "expense", "2026-10-01")
        ).status_code
        == 422
    )
    mismatch = alice.post("/api/transactions", json=payload(groceries, 100, "income", "2026-10-01"))
    assert mismatch.status_code == 422
    bad_range = alice.get(
        "/api/transactions", params={"date_from": "2026-10-02", "date_to": "2026-10-01"}
    )
    assert bad_range.status_code == 422


def test_update_transaction(alice: User, ledger) -> None:
    tx = ledger["groceries"]
    restaurants = alice.category_ids()["Restaurants & cafes"]

    response = alice.put(
        f"/api/transactions/{tx['id']}",
        json=payload(restaurants, 9_999_00, "expense", "2026-10-11", "Dinner"),
    )

    assert response.status_code == 200
    updated = response.json()
    assert (updated["amount_cents"], updated["description"], updated["occurred_on"]) == (
        9_999_00,
        "Dinner",
        "2026-10-11",
    )
    assert updated["category"]["name"] == "Restaurants & cafes"
    assert alice.get(f"/api/transactions/{tx['id']}").json() == updated


def test_delete_transaction(alice: User, ledger) -> None:
    tx = ledger["bus"]

    assert alice.delete(f"/api/transactions/{tx['id']}").status_code == 204
    assert alice.get(f"/api/transactions/{tx['id']}").status_code == 404
    assert alice.delete(f"/api/transactions/{tx['id']}").status_code == 404
    assert alice.get("/api/transactions").json()["total"] == 2


def test_category_in_use_cannot_be_deleted(alice: User, ledger) -> None:
    category_id = ledger["salary"]["category_id"]

    assert alice.delete(f"/api/categories/{category_id}").status_code == 409


def test_another_user_cannot_read_change_or_delete_a_transaction(
    alice: User, bob: User, ledger
) -> None:
    tx = ledger["groceries"]
    bob_groceries = bob.category_ids()["Groceries"]

    read = bob.get(f"/api/transactions/{tx['id']}")
    assert read.status_code == 404
    assert read.json() == {"detail": f"Transaction {tx['id']} not found"}
    hijack = payload(bob_groceries, 1, "expense", "2026-01-01", "hijacked")
    assert bob.put(f"/api/transactions/{tx['id']}", json=hijack).status_code == 404
    assert bob.delete(f"/api/transactions/{tx['id']}").status_code == 404

    assert alice.get(f"/api/transactions/{tx['id']}").json() == tx  # untouched


def test_lists_and_filters_never_include_another_users_data(alice: User, bob: User, ledger) -> None:
    alice_salary = ledger["salary"]["category_id"]

    assert bob.get("/api/transactions").json()["total"] == 0
    assert bob.get("/api/transactions", params={"category_id": alice_salary}).json()["total"] == 0
    # Made-up owner parameters and headers are ignored.
    assert bob.get("/api/transactions", params={"user_id": 1}).json()["total"] == 0
    assert bob.get("/api/transactions", headers={"X-User-Id": "1"}).json()["total"] == 0


def test_another_users_category_cannot_be_used(alice: User, bob: User, ledger) -> None:
    alice_groceries = ledger["groceries"]["category_id"]

    response = bob.post(
        "/api/transactions", json=payload(alice_groceries, 100, "expense", "2026-10-01")
    )

    assert response.status_code == 422
    assert response.json() == {"detail": f"Category {alice_groceries} does not exist"}
    mine = create(bob, bob.category_ids()["Groceries"], 100, "expense", "2026-10-01")
    moved = bob.put(
        f"/api/transactions/{mine['id']}",
        json=payload(alice_groceries, 100, "expense", "2026-10-01"),
    )
    assert moved.status_code == 422


def test_owner_cannot_be_set_through_the_body(bob: User) -> None:
    body = {**payload(bob.category_ids()["Groceries"], 100, "expense", "2026-10-01"), "user_id": 1}

    assert bob.post("/api/transactions", json=body).status_code == 422


def test_guessing_ids_finds_nothing(alice: User, bob: User, ledger) -> None:
    highest = max(tx["id"] for tx in ledger.values())

    for tx_id in range(1, highest + 1):
        assert bob.get(f"/api/transactions/{tx_id}").status_code == 404
