"""Default categories. Run with:  uv run python -m app.seed

Seeding only happens when the categories table is empty, so categories a user deleted
do not come back every time the command runs.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, TransactionType

DEFAULT_CATEGORIES: list[tuple[str, TransactionType, str]] = [
    ("Salary", TransactionType.INCOME, "#16a34a"),
    ("Freelance", TransactionType.INCOME, "#22c55e"),
    ("Gifts", TransactionType.INCOME, "#84cc16"),
    ("Other income", TransactionType.INCOME, "#65a30d"),
    ("Groceries", TransactionType.EXPENSE, "#f97316"),
    ("Restaurants & cafes", TransactionType.EXPENSE, "#ef4444"),
    ("Transport", TransactionType.EXPENSE, "#3b82f6"),
    ("Housing & utilities", TransactionType.EXPENSE, "#8b5cf6"),
    ("Health", TransactionType.EXPENSE, "#ec4899"),
    ("Entertainment", TransactionType.EXPENSE, "#eab308"),
    ("Shopping", TransactionType.EXPENSE, "#14b8a6"),
    ("Education", TransactionType.EXPENSE, "#6366f1"),
    ("Other expenses", TransactionType.EXPENSE, "#64748b"),
]


def seed_default_categories(db: Session) -> int:
    """Insert the default categories if there are none. Returns how many were added."""
    if (db.scalar(select(func.count(Category.id))) or 0) > 0:
        return 0
    db.add_all(
        Category(name=name, type=type_, color=color, is_default=True)
        for name, type_, color in DEFAULT_CATEGORIES
    )
    db.commit()
    return len(DEFAULT_CATEGORIES)


if __name__ == "__main__":
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        added = seed_default_categories(session)
    print(f"Seeded {added} default categories." if added else "Categories exist; nothing seeded.")
