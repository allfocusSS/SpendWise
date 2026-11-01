"""The database enforces money, category and ownership rules, even if services are bypassed."""

from datetime import date

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Category, Transaction, User
from app.services import auth as auth_service
from tests.conftest import PASSWORD


def groceries(db: Session, user_id: int) -> Category:
    return db.scalars(
        select(Category).where(Category.name == "Groceries", Category.user_id == user_id)
    ).one()


def expense(user_id: int, category_id: int, amount: int = 100) -> Transaction:
    return Transaction(
        user_id=user_id,
        amount_cents=amount,
        type="expense",
        category_id=category_id,
        description="x",
        occurred_on=date(2026, 10, 1),
    )


def test_foreign_key_blocks_deleting_used_category(db: Session, user_id: int) -> None:
    category = groceries(db, user_id)
    db.add(expense(user_id, category.id))
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(delete(Category).where(Category.id == category.id))
        db.commit()


@pytest.mark.parametrize("amount", [0, -1])
def test_check_constraint_blocks_non_positive_amounts(
    db: Session, user_id: int, amount: int
) -> None:
    db.add(expense(user_id, groceries(db, user_id).id, amount))

    with pytest.raises(IntegrityError):
        db.commit()


def test_transaction_cannot_use_another_users_category(db: Session, user_id: int) -> None:
    # Even with the service layer bypassed, the composite foreign key refuses the link.
    other = auth_service.create_user(db, "other@example.com", PASSWORD)
    db.add(expense(user_id, groceries(db, other.id).id))

    with pytest.raises(IntegrityError):
        db.commit()


def test_category_names_are_unique_per_user_not_globally(db: Session, user_id: int) -> None:
    other = auth_service.create_user(db, "other@example.com", PASSWORD)
    assert groceries(db, other.id).id != groceries(db, user_id).id  # both have "Groceries"

    db.add(Category(user_id=user_id, name="Groceries", type="expense", color="#000000"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_emails_are_unique(db: Session, user_id: int) -> None:
    db.add(User(email="db-user@example.com", password_hash="x"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_a_user_removes_only_their_data(db: Session, user_id: int) -> None:
    other = auth_service.create_user(db, "other@example.com", PASSWORD)
    db.add_all(
        [expense(user_id, groceries(db, user_id).id), expense(other.id, groceries(db, other.id).id)]
    )
    db.commit()

    db.execute(delete(User).where(User.id == user_id))
    db.commit()

    owners = db.scalars(select(Transaction.user_id)).all()
    assert owners == [other.id]
    assert db.scalar(select(func.count()).where(Category.user_id == user_id)) == 0
    assert db.scalar(select(func.count()).where(Category.user_id == other.id)) > 0
