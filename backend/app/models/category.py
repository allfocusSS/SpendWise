from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class Category(TimestampMixin, Base):
    """Every category belongs to one user. "Default" categories are per-user copies made at
    signup (is_default=True), so one user renaming or deleting them never affects another."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", "type"),
        # Target of the transactions (category_id, user_id) foreign key: a transaction can only
        # point at a category owned by the same user.
        UniqueConstraint("id", "user_id"),
        CheckConstraint("type IN ('income', 'expense')", name="type_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    type: Mapped[str] = mapped_column(String(10))
    color: Mapped[str] = mapped_column(String(7), default="#64748b")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # viewonly: transactions are linked by setting category_id/user_id, never through this
    # collection, and the ORM never touches them when a category is deleted (the DB decides).
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="category", viewonly=True
    )
