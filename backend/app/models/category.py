from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("name", "type"),
        CheckConstraint("type IN ('income', 'expense')", name="type_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    type: Mapped[str] = mapped_column(String(10))
    color: Mapped[str] = mapped_column(String(7), default="#64748b")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # passive_deletes="all": never let the ORM null out transactions; the DB RESTRICT rule decides.
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="category", passive_deletes="all"
    )
