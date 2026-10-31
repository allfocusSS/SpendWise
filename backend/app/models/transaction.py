from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.category import Category


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="amount_positive"),
        CheckConstraint("type IN ('income', 'expense')", name="type_valid"),
        CheckConstraint("source IN ('manual', 'ai')", name="source_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Money is always a positive whole number of cents (tiyn); `type` says which direction.
    # BigInteger because a 32-bit INTEGER overflows at ~21.4M KZT.
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    type: Mapped[str] = mapped_column(String(10))
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str] = mapped_column(String(255))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")

    category: Mapped[Category] = relationship(back_populates="transactions")
