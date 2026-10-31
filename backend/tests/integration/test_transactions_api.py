import pytest
from fastapi.testclient import TestClient


def payload(category_id: int, **overrides) -> dict:
    return {
        "amount_cents": 250_000,  # 2 500.00 ₸
        "type": "expense",
        "category_id": category_id,
        "description": "Weekly groceries",
        "occurred_on": "2026-10-15",
        **overrides,
    }


def create(client: TestClient, body: dict) -> dict:
    response = client.post("/api/transactions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_transaction(client: TestClient, category_ids) -> None:
    created = create(client, payload(category_ids["Groceries"]))

    assert created["amount_cents"] == 250_000
    assert created["category"]["name"] == "Groceries"
    assert created["source"] == "manual"

    fetched = client.get(f"/api/transactions/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_update_transaction_replaces_fields(client: TestClient, category_ids) -> None:
    created = create(client, payload(category_ids["Groceries"]))

    response = client.put(
        f"/api/transactions/{created['id']}",
        json=payload(
            category_ids["Transport"],
            amount_cents=80_000,
            description="Taxi",
            occurred_on="2026-10-16",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["amount_cents"] == 80_000
    assert body["description"] == "Taxi"
    assert body["occurred_on"] == "2026-10-16"
    assert body["category_id"] == category_ids["Transport"]
    assert body["category"]["name"] == "Transport"


def test_delete_transaction(client: TestClient, category_ids) -> None:
    created = create(client, payload(category_ids["Groceries"]))

    assert client.delete(f"/api/transactions/{created['id']}").status_code == 204
    assert client.get(f"/api/transactions/{created['id']}").status_code == 404


def test_missing_transaction_returns_404(client: TestClient, category_ids) -> None:
    assert client.get("/api/transactions/9999").status_code == 404
    assert (
        client.put("/api/transactions/9999", json=payload(category_ids["Groceries"])).status_code
        == 404
    )
    assert client.delete("/api/transactions/9999").status_code == 404


def test_unknown_category_returns_422(client: TestClient) -> None:
    response = client.post("/api/transactions", json=payload(9999))

    assert response.status_code == 422
    assert response.json()["detail"] == "Category 9999 does not exist"


def test_category_type_must_match_transaction_type(client: TestClient, category_ids) -> None:
    response = client.post("/api/transactions", json=payload(category_ids["Salary"]))

    assert response.status_code == 422
    assert "is for income" in response.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount_cents": 0},
        {"amount_cents": -500},
        {"amount_cents": 99.99},
        {"amount_cents": "1000"},
        {"description": ""},
        {"occurred_on": "not-a-date"},
        {"type": "transfer"},
        {"unexpected": "field"},
    ],
)
def test_invalid_input_returns_422(client: TestClient, category_ids, overrides: dict) -> None:
    response = client.post(
        "/api/transactions", json=payload(category_ids["Groceries"], **overrides)
    )

    assert response.status_code == 422


class TestListing:
    @pytest.fixture
    def seeded(self, client: TestClient, category_ids) -> None:
        create(client, payload(category_ids["Groceries"], occurred_on="2026-09-10"))
        create(client, payload(category_ids["Transport"], occurred_on="2026-10-01"))
        create(
            client,
            payload(
                category_ids["Salary"],
                type="income",
                amount_cents=500_000_00,
                occurred_on="2026-10-05",
            ),
        )

    def test_lists_newest_first_with_total(self, client: TestClient, seeded) -> None:
        body = client.get("/api/transactions").json()

        assert body["total"] == 3
        assert [t["occurred_on"] for t in body["items"]] == [
            "2026-10-05",
            "2026-10-01",
            "2026-09-10",
        ]

    def test_filters_by_date_range(self, client: TestClient, seeded) -> None:
        body = client.get(
            "/api/transactions", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}
        ).json()

        assert body["total"] == 2

    def test_filters_by_type_and_category(self, client: TestClient, seeded, category_ids) -> None:
        by_type = client.get("/api/transactions", params={"type": "income"}).json()
        by_category = client.get(
            "/api/transactions", params={"category_id": category_ids["Transport"]}
        ).json()

        assert by_type["total"] == 1 and by_type["items"][0]["type"] == "income"
        assert by_category["total"] == 1

    def test_pagination(self, client: TestClient, seeded) -> None:
        body = client.get("/api/transactions", params={"limit": 2, "offset": 2}).json()

        assert body["total"] == 3
        assert len(body["items"]) == 1
        assert body["limit"] == 2 and body["offset"] == 2

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 201},
            {"offset": -1},
            {"date_from": "2026-10-31", "date_to": "2026-10-01"},
        ],
    )
    def test_invalid_list_params_return_422(self, client: TestClient, params: dict) -> None:
        assert client.get("/api/transactions", params=params).status_code == 422
