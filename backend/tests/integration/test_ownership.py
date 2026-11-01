"""Per-user isolation: Bob can never read, change or infer Alice's data.

Alice (`client`) and Bob (`other_client`) are two signed-in users of the same app and database.
Another user's row must behave exactly like a row that does not exist.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import SESSION_COOKIE


def make_transaction(
    client: TestClient, category_id: int, amount: int, type_: str = "expense", day="2026-10-10"
) -> dict:
    response = client.post(
        "/api/transactions",
        json={
            "amount_cents": amount,
            "type": type_,
            "category_id": category_id,
            "description": "private",
            "occurred_on": day,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def ids(client: TestClient) -> dict[str, int]:
    return {c["name"]: c["id"] for c in client.get("/api/categories").json()}


@pytest.fixture
def alice_data(client: TestClient) -> dict:
    """Alice's transactions and a private category, all created through the API."""
    cats = ids(client)
    private = client.post(
        "/api/categories", json={"name": "Therapy", "type": "expense", "color": "#123456"}
    ).json()
    return {
        "category": private,
        "salary": make_transaction(client, cats["Salary"], 900_000_00, "income", "2026-10-01"),
        "expense": make_transaction(client, private["id"], 40_000_00),
    }


def missing_transaction_id(alice_data: dict) -> int:
    return max(alice_data["salary"]["id"], alice_data["expense"]["id"]) + 1000


# --- Transactions ------------------------------------------------------------------------------


def test_bob_cannot_read_alices_transaction(alice_data, other_client: TestClient) -> None:
    tx = alice_data["expense"]
    response = other_client.get(f"/api/transactions/{tx['id']}")

    # Exactly what a non-existent id returns: nothing tells Bob the row exists.
    nonexistent = other_client.get(f"/api/transactions/{missing_transaction_id(alice_data)}")
    assert response.status_code == nonexistent.status_code == 404
    assert response.json() == {"detail": f"Transaction {tx['id']} not found"}


def test_bob_cannot_update_alices_transaction(
    alice_data, client: TestClient, other_client: TestClient
) -> None:
    tx = alice_data["expense"]
    bob_groceries = ids(other_client)["Groceries"]

    for category_id in (bob_groceries, tx["category_id"]):
        response = other_client.put(
            f"/api/transactions/{tx['id']}",
            json={
                "amount_cents": 1,
                "type": "expense",
                "category_id": category_id,
                "description": "hijacked",
                "occurred_on": "2026-01-01",
            },
        )
        assert response.status_code == 404

    assert client.get(f"/api/transactions/{tx['id']}").json() == tx  # untouched


def test_bob_cannot_delete_alices_transaction(
    alice_data, client: TestClient, other_client: TestClient
) -> None:
    tx = alice_data["expense"]

    assert other_client.delete(f"/api/transactions/{tx['id']}").status_code == 404
    assert client.get(f"/api/transactions/{tx['id']}").status_code == 200


def test_lists_only_show_your_own_transactions(
    alice_data, client: TestClient, other_client: TestClient
) -> None:
    mine = make_transaction(other_client, ids(other_client)["Groceries"], 5_000_00)

    bob = other_client.get("/api/transactions").json()
    assert bob["total"] == 1
    assert [t["id"] for t in bob["items"]] == [mine["id"]]

    alice = client.get("/api/transactions").json()
    assert {t["id"] for t in alice["items"]} == {
        alice_data["salary"]["id"],
        alice_data["expense"]["id"],
    }


def test_filtering_by_alices_category_shows_bob_nothing(
    alice_data, other_client: TestClient
) -> None:
    category_id = alice_data["category"]["id"]
    body = other_client.get("/api/transactions", params={"category_id": category_id}).json()

    assert body["total"] == 0
    assert body["items"] == []


def test_bob_cannot_file_a_transaction_under_alices_category(
    alice_data, other_client: TestClient
) -> None:
    category_id = alice_data["category"]["id"]
    payload = {
        "amount_cents": 100,
        "type": "expense",
        "category_id": category_id,
        "description": "x",
        "occurred_on": "2026-10-10",
    }

    created = other_client.post("/api/transactions", json=payload)
    assert created.status_code == 422
    assert created.json() == {"detail": f"Category {category_id} does not exist"}

    mine = make_transaction(other_client, ids(other_client)["Groceries"], 100)
    moved = other_client.put(f"/api/transactions/{mine['id']}", json=payload)
    assert moved.status_code == 422
    assert other_client.get(f"/api/transactions/{mine['id']}").json() == mine


def test_guessing_ids_finds_nothing(alice_data, other_client: TestClient) -> None:
    for tx_id in range(1, missing_transaction_id(alice_data)):
        assert other_client.get(f"/api/transactions/{tx_id}").status_code == 404


# --- Categories --------------------------------------------------------------------------------


def test_bob_cannot_see_alices_private_category(alice_data, other_client: TestClient) -> None:
    category = alice_data["category"]

    assert category["id"] not in {c["id"] for c in other_client.get("/api/categories").json()}
    assert "Therapy" not in ids(other_client)
    response = other_client.get(f"/api/categories/{category['id']}")
    assert response.status_code == 404
    assert response.json() == {"detail": f"Category {category['id']} not found"}


def test_bob_cannot_rename_or_delete_alices_categories(
    alice_data, client: TestClient, other_client: TestClient
) -> None:
    private = alice_data["category"]
    alice_default = ids(client)["Groceries"]

    for category_id in (private["id"], alice_default):
        assert (
            other_client.patch(f"/api/categories/{category_id}", json={"name": "x"}).status_code
            == 404
        )
        assert other_client.delete(f"/api/categories/{category_id}").status_code == 404

    assert client.get(f"/api/categories/{private['id']}").json() == private
    assert "Groceries" in ids(client)


def test_category_names_are_per_user(alice_data, other_client: TestClient) -> None:
    # Alice already has "Therapy"; Bob can create his own, and duplicates only clash per user.
    created = other_client.post("/api/categories", json={"name": "therapy", "type": "expense"})
    assert created.status_code == 201
    assert created.json()["id"] != alice_data["category"]["id"]

    again = other_client.post("/api/categories", json={"name": "THERAPY", "type": "expense"})
    assert again.status_code == 409


def test_deleting_a_category_ignores_other_users_transactions(
    alice_data, client: TestClient, other_client: TestClient
) -> None:
    # Bob's categories have no transactions, whatever Alice has filed under her own.
    bob_custom = other_client.post("/api/categories", json={"name": "Therapy", "type": "expense"})
    assert other_client.delete(f"/api/categories/{bob_custom.json()['id']}").status_code == 204
    # And Alice's category is still protected by her own transaction.
    assert client.delete(f"/api/categories/{alice_data['category']['id']}").status_code == 409


# --- Analytics ---------------------------------------------------------------------------------


def test_bob_sees_none_of_alices_numbers(alice_data, other_client: TestClient) -> None:
    summary = other_client.get("/api/analytics/summary").json()
    assert summary["total_income_cents"] == 0
    assert summary["total_expense_cents"] == 0
    assert summary["transaction_count"] == 0

    for type_ in ("income", "expense"):
        breakdown = other_client.get("/api/analytics/by-category", params={"type": type_}).json()
        assert breakdown["total_cents"] == 0
        assert breakdown["items"] == []

    trend = other_client.get(
        "/api/analytics/monthly-trend", params={"months": 3, "until": "2026-10-31"}
    ).json()
    assert all(m["income_cents"] == m["expense_cents"] == 0 for m in trend["months"])


def test_each_user_gets_their_own_totals(
    alice_data, client: TestClient, other_client: TestClient
) -> None:
    make_transaction(other_client, ids(other_client)["Salary"], 300_000_00, "income")
    make_transaction(other_client, ids(other_client)["Groceries"], 12_000_00)

    alice = client.get("/api/analytics/summary").json()
    bob = other_client.get("/api/analytics/summary").json()
    assert (alice["total_income_cents"], alice["total_expense_cents"]) == (900_000_00, 40_000_00)
    assert (bob["total_income_cents"], bob["total_expense_cents"]) == (300_000_00, 12_000_00)

    alice_names = {
        i["category_name"]
        for i in client.get("/api/analytics/by-category", params={"type": "expense"}).json()[
            "items"
        ]
    }
    bob_names = {
        i["category_name"]
        for i in other_client.get("/api/analytics/by-category", params={"type": "expense"}).json()[
            "items"
        ]
    }
    assert alice_names == {"Therapy"}
    assert bob_names == {"Groceries"}

    trend = other_client.get(
        "/api/analytics/monthly-trend", params={"months": 1, "until": "2026-10-31"}
    ).json()
    assert trend["months"] == [
        {
            "month": "2026-10",
            "income_cents": 300_000_00,
            "expense_cents": 12_000_00,
            "net_cents": 288_000_00,
        }
    ]


# --- Tampering ---------------------------------------------------------------------------------


def test_owner_cannot_be_set_through_the_body(alice_data, other_client: TestClient) -> None:
    alice_id = 1  # Alice signed up first
    groceries = ids(other_client)["Groceries"]
    base = {
        "amount_cents": 100,
        "type": "expense",
        "category_id": groceries,
        "description": "x",
        "occurred_on": "2026-10-10",
    }

    assert (
        other_client.post("/api/transactions", json={**base, "user_id": alice_id}).status_code
        == 422
    )
    mine = make_transaction(other_client, groceries, 100)
    for extra in ({"user_id": alice_id}, {"id": alice_data["expense"]["id"]}):
        response = other_client.put(f"/api/transactions/{mine['id']}", json={**base, **extra})
        assert response.status_code == 422
    assert (
        other_client.post(
            "/api/categories", json={"name": "Mine", "type": "expense", "user_id": alice_id}
        ).status_code
        == 422
    )
    assert (
        other_client.patch(f"/api/categories/{groceries}", json={"user_id": alice_id}).status_code
        == 422
    )


def test_owner_cannot_be_chosen_with_query_parameters_or_headers(
    alice_data, other_client: TestClient
) -> None:
    for params in ({"user_id": 1}, {"owner": 1}, {"user": "alice@example.com"}):
        assert other_client.get("/api/transactions", params=params).json()["total"] == 0
        assert (
            other_client.get("/api/analytics/summary", params=params).json()["transaction_count"]
            == 0
        )
    headers = {"X-User-Id": "1", "X-Forwarded-User": "alice@example.com"}
    assert other_client.get("/api/transactions", headers=headers).json()["total"] == 0


def test_alices_cookie_does_not_survive_her_logout(alice_data, client: TestClient, app) -> None:
    stolen = client.cookies[SESSION_COOKIE]
    client.post("/api/auth/logout")

    thief = TestClient(app, cookies={SESSION_COOKIE: stolen})
    assert thief.get(f"/api/transactions/{alice_data['expense']['id']}").status_code == 401
    assert thief.get("/api/analytics/summary").status_code == 401
