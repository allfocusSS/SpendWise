"""Categories over real HTTP: per-user defaults, custom categories, isolation between users."""

from integration.conftest import User

DEFAULTS = {
    "income": {"Salary", "Freelance", "Gifts", "Other income"},
    "expense": {
        "Groceries",
        "Restaurants & cafes",
        "Transport",
        "Housing & utilities",
        "Health",
        "Entertainment",
        "Shopping",
        "Education",
        "Other expenses",
    },
}


def test_new_account_has_the_default_categories(alice: User) -> None:
    categories = alice.get("/api/categories").json()

    assert {c["name"] for c in categories if c["type"] == "income"} == DEFAULTS["income"]
    assert {c["name"] for c in categories if c["type"] == "expense"} == DEFAULTS["expense"]
    assert all(c["is_default"] for c in categories)


def test_list_can_be_filtered_by_type(alice: User) -> None:
    income = alice.get("/api/categories", params={"type": "income"}).json()

    assert {c["name"] for c in income} == DEFAULTS["income"]


def test_create_list_update_and_delete_a_custom_category(alice: User) -> None:
    created = alice.post(
        "/api/categories", json={"name": " Pets ", "type": "expense", "color": "#AA5500"}
    )
    assert created.status_code == 201
    pets = created.json()
    assert (pets["name"], pets["is_default"], pets["color"]) == ("Pets", False, "#AA5500")

    assert pets in alice.get("/api/categories").json()
    assert alice.get(f"/api/categories/{pets['id']}").json() == pets

    renamed = alice.patch(f"/api/categories/{pets['id']}", json={"name": "Pet care"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Pet care"

    assert alice.delete(f"/api/categories/{pets['id']}").status_code == 204
    assert alice.get(f"/api/categories/{pets['id']}").status_code == 404


def test_duplicate_names_clash_per_user_ignoring_case(alice: User) -> None:
    response = alice.post("/api/categories", json={"name": "GROCERIES", "type": "expense"})

    assert response.status_code == 409


def test_users_cannot_see_or_change_each_others_categories(alice: User, bob: User) -> None:
    private = alice.post("/api/categories", json={"name": "Therapy", "type": "expense"}).json()
    alice_groceries = alice.category_ids()["Groceries"]

    assert private["id"] not in {c["id"] for c in bob.get("/api/categories").json()}
    assert alice_groceries not in bob.category_ids().values()  # Bob has his own copy
    for category_id in (private["id"], alice_groceries):
        assert bob.get(f"/api/categories/{category_id}").status_code == 404
        assert bob.patch(f"/api/categories/{category_id}", json={"name": "x"}).status_code == 404
        assert bob.delete(f"/api/categories/{category_id}").status_code == 404

    assert alice.get(f"/api/categories/{private['id']}").json() == private
    assert "Groceries" in alice.category_ids()


def test_same_custom_name_is_allowed_for_different_users(alice: User, bob: User) -> None:
    mine = alice.post("/api/categories", json={"name": "Garden", "type": "expense"})
    theirs = bob.post("/api/categories", json={"name": "Garden", "type": "expense"})

    assert mine.status_code == theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]


def test_owner_cannot_be_set_through_the_body(bob: User) -> None:
    response = bob.post("/api/categories", json={"name": "Sneaky", "type": "expense", "user_id": 1})

    assert response.status_code == 422
