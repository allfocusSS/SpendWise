from fastapi.testclient import TestClient

from app.seed import DEFAULT_CATEGORIES


def create_expense(client: TestClient, category_id: int, amount_cents: int = 10_000) -> dict:
    response = client.post(
        "/api/transactions",
        json={
            "amount_cents": amount_cents,
            "type": "expense",
            "category_id": category_id,
            "description": "Test expense",
            "occurred_on": "2026-10-01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_lists_seeded_default_categories(client: TestClient) -> None:
    response = client.get("/api/categories")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(DEFAULT_CATEGORIES)
    assert all(c["is_default"] for c in body)


def test_filters_categories_by_type(client: TestClient) -> None:
    body = client.get("/api/categories", params={"type": "income"}).json()

    assert body and all(c["type"] == "income" for c in body)


def test_create_get_update_delete_category(client: TestClient) -> None:
    created = client.post(
        "/api/categories", json={"name": "  Pets ", "type": "expense", "color": "#AA5500"}
    )
    assert created.status_code == 201
    category = created.json()
    assert category["name"] == "Pets"  # trimmed
    assert category["is_default"] is False

    fetched = client.get(f"/api/categories/{category['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == category

    updated = client.patch(f"/api/categories/{category['id']}", json={"name": "Pet care"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Pet care"
    assert updated.json()["color"] == "#AA5500"  # untouched

    deleted = client.delete(f"/api/categories/{category['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/categories/{category['id']}").status_code == 404


def test_duplicate_name_same_type_is_conflict_case_insensitive(client: TestClient) -> None:
    response = client.post("/api/categories", json={"name": "groceries", "type": "expense"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_same_name_different_type_is_allowed(client: TestClient) -> None:
    response = client.post("/api/categories", json={"name": "Groceries", "type": "income"})

    assert response.status_code == 201


def test_rename_to_existing_name_is_conflict(client: TestClient, category_ids) -> None:
    response = client.patch(
        f"/api/categories/{category_ids['Transport']}", json={"name": "Groceries"}
    )

    assert response.status_code == 409


def test_cannot_delete_category_used_by_transactions(client: TestClient, category_ids) -> None:
    create_expense(client, category_ids["Groceries"])

    response = client.delete(f"/api/categories/{category_ids['Groceries']}")

    assert response.status_code == 409
    assert "used by 1 transaction" in response.json()["detail"]
    assert client.get(f"/api/categories/{category_ids['Groceries']}").status_code == 200


def test_cannot_change_type_of_used_category(client: TestClient, category_ids) -> None:
    create_expense(client, category_ids["Groceries"])

    response = client.patch(f"/api/categories/{category_ids['Groceries']}", json={"type": "income"})

    assert response.status_code == 409


def test_can_change_type_of_unused_category(client: TestClient, category_ids) -> None:
    response = client.patch(f"/api/categories/{category_ids['Education']}", json={"type": "income"})

    assert response.status_code == 200
    assert response.json()["type"] == "income"


def test_unknown_category_returns_404(client: TestClient) -> None:
    assert client.get("/api/categories/9999").status_code == 404
    assert client.patch("/api/categories/9999", json={"name": "X"}).status_code == 404
    assert client.delete("/api/categories/9999").status_code == 404


def test_invalid_category_payload_returns_422(client: TestClient) -> None:
    assert client.post("/api/categories", json={"name": "", "type": "expense"}).status_code == 422
    assert client.post("/api/categories", json={"name": "X", "type": "loan"}).status_code == 422
    assert (
        client.post(
            "/api/categories", json={"name": "X", "type": "expense", "color": "blue"}
        ).status_code
        == 422
    )
