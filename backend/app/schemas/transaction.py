from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import TransactionSource, TransactionType
from app.schemas.category import CategoryRead
from app.schemas.common import AmountCents, NonEmptyStr255


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: AmountCents
    type: TransactionType
    category_id: int
    description: NonEmptyStr255
    occurred_on: date
    source: TransactionSource = TransactionSource.MANUAL


class TransactionUpdate(TransactionCreate):
    """PUT replaces the whole transaction, so it takes the same fields as create."""


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount_cents: int
    type: TransactionType
    category_id: int
    category: CategoryRead
    description: str
    occurred_on: date
    source: TransactionSource
    created_at: datetime
    updated_at: datetime


class TransactionList(BaseModel):
    items: list[TransactionRead]
    total: int
    limit: int
    offset: int
