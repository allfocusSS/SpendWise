"""Default categories are per-user copies, created at signup."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category
from app.seed import DEFAULT_CATEGORIES, seed_default_categories


def count(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count(Category.id)).where(Category.user_id == user_id)) or 0


def test_new_user_gets_the_defaults(db: Session, user_id: int) -> None:
    assert count(db, user_id) == len(DEFAULT_CATEGORIES)
    assert all(
        c.is_default for c in db.scalars(select(Category).where(Category.user_id == user_id))
    )


def test_seed_does_nothing_when_the_user_has_categories(db: Session, user_id: int) -> None:
    assert seed_default_categories(db, user_id) == 0
    assert count(db, user_id) == len(DEFAULT_CATEGORIES)


def test_seed_fills_an_empty_account(db: Session, user_id: int) -> None:
    db.query(Category).filter(Category.user_id == user_id).delete()
    db.commit()

    assert seed_default_categories(db, user_id) == len(DEFAULT_CATEGORIES)


def test_each_user_has_an_independent_copy(client: TestClient, other_client: TestClient) -> None:
    alice = {c["name"]: c for c in client.get("/api/categories").json()}
    bob = {c["name"]: c for c in other_client.get("/api/categories").json()}
    assert alice.keys() == bob.keys()
    assert {c["id"] for c in alice.values()}.isdisjoint(c["id"] for c in bob.values())

    # Alice renames and deletes her defaults; Bob's stay as they were.
    client.patch(f"/api/categories/{alice['Groceries']['id']}", json={"name": "Food"})
    client.delete(f"/api/categories/{alice['Gifts']['id']}")

    bob_after = {c["name"] for c in other_client.get("/api/categories").json()}
    assert bob_after == bob.keys()
