"""The database itself enforces money and category rules, even if service checks are bypassed."""

from datetime import date

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Category, Transaction


def groceries(db: Session) -> Category:
    return db.scalars(select(Category).where(Category.name == "Groceries")).one()


def test_foreign_key_blocks_deleting_used_category(db: Session) -> None:
    category = groceries(db)
    db.add(
        Transaction(
            amount_cents=100,
            type="expense",
            category_id=category.id,
            description="x",
            occurred_on=date(2026, 10, 1),
        )
    )
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(delete(Category).where(Category.id == category.id))
        db.commit()


@pytest.mark.parametrize("amount", [0, -1])
def test_check_constraint_blocks_non_positive_amounts(db: Session, amount: int) -> None:
    db.add(
        Transaction(
            amount_cents=amount,
            type="expense",
            category_id=groceries(db).id,
            description="x",
            occurred_on=date(2026, 10, 1),
        )
    )

    with pytest.raises(IntegrityError):
        db.commit()
