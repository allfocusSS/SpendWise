"""Importing this package registers every model on Base.metadata (needed by Alembic and tests)."""

from app.models.base import Base, TransactionSource, TransactionType
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import User, UserSession

__all__ = [
    "Base",
    "Category",
    "Transaction",
    "TransactionSource",
    "TransactionType",
    "User",
    "UserSession",
]
