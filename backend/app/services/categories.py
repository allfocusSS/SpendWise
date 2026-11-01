"""Categories, always scoped to one user.

Every query filters by user_id, so another user's category behaves exactly like one that does
not exist (404), and its id reveals nothing.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import Category, Transaction, TransactionType
from app.schemas.category import CategoryCreate, CategoryUpdate


def list_categories(
    db: Session, user_id: int, type_: TransactionType | None = None
) -> list[Category]:
    query = (
        select(Category).where(Category.user_id == user_id).order_by(Category.type, Category.name)
    )
    if type_ is not None:
        query = query.where(Category.type == type_)
    return list(db.scalars(query))


def get_category(db: Session, user_id: int, category_id: int) -> Category:
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.user_id == user_id)
    )
    if category is None:
        raise NotFoundError(f"Category {category_id} not found")
    return category


def create_category(db: Session, user_id: int, data: CategoryCreate) -> Category:
    _ensure_name_is_free(db, user_id, data.name, data.type)
    category = Category(user_id=user_id, name=data.name, type=data.type, color=data.color)
    db.add(category)
    db.commit()
    return category


def update_category(db: Session, user_id: int, category_id: int, data: CategoryUpdate) -> Category:
    category = get_category(db, user_id, category_id)
    changes = data.model_dump(exclude_unset=True)

    new_type = changes.get("type", category.type)
    if new_type != category.type and _count_transactions(db, user_id, category_id) > 0:
        raise ConflictError("Cannot change the type of a category that has transactions")

    new_name = changes.get("name", category.name)
    if (new_name, new_type) != (category.name, category.type):
        _ensure_name_is_free(db, user_id, new_name, new_type, exclude_id=category_id)

    for field, value in changes.items():
        setattr(category, field, value)
    db.commit()
    return category


def delete_category(db: Session, user_id: int, category_id: int) -> None:
    category = get_category(db, user_id, category_id)
    used_by = _count_transactions(db, user_id, category_id)
    if used_by > 0:
        raise ConflictError(
            f"Category is used by {used_by} transaction(s); reassign or delete them first"
        )
    db.delete(category)
    db.commit()


def _count_transactions(db: Session, user_id: int, category_id: int) -> int:
    query = select(func.count()).where(
        Transaction.category_id == category_id, Transaction.user_id == user_id
    )
    return db.scalar(query) or 0


def _ensure_name_is_free(
    db: Session, user_id: int, name: str, type_: str, exclude_id: int | None = None
) -> None:
    """Names are unique per user and type, ignoring case ("Food" and "food" clash)."""
    query = select(Category.id).where(
        Category.user_id == user_id,
        func.lower(Category.name) == name.lower(),
        Category.type == type_,
    )
    if exclude_id is not None:
        query = query.where(Category.id != exclude_id)
    if db.scalar(query) is not None:
        raise ConflictError(f"A {type_} category named '{name}' already exists")
