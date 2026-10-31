from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category
from app.seed import DEFAULT_CATEGORIES, seed_default_categories


def test_seed_does_nothing_when_categories_exist(db: Session) -> None:
    # The fixture already seeded once; a second run must not duplicate anything.
    assert seed_default_categories(db) == 0
    assert db.scalar(select(func.count(Category.id))) == len(DEFAULT_CATEGORIES)


def test_seed_fills_an_empty_table(db: Session) -> None:
    db.query(Category).delete()
    db.commit()

    assert seed_default_categories(db) == len(DEFAULT_CATEGORIES)
