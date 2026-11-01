"""Default categories, copied into every new account at signup (see app.services.auth).

Each user owns their copy, so renaming or deleting a default only affects that user.
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


def seed_default_categories(db: Session, user_id: int) -> int:
    """Add the default categories for a user who has none. Returns how many were added.

    Does not commit: account creation commits the user and their categories together.
    """
    existing = db.scalar(select(func.count(Category.id)).where(Category.user_id == user_id))
    if existing:
        return 0
    db.add_all(
        Category(user_id=user_id, name=name, type=type_, color=color, is_default=True)
        for name, type_, color in DEFAULT_CATEGORIES
    )
    db.flush()
    return len(DEFAULT_CATEGORIES)
