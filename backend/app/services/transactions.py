from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Category, Transaction, TransactionType
from app.schemas.transaction import TransactionCreate, TransactionUpdate


@dataclass
class TransactionFilters:
    date_from: date | None = None
    date_to: date | None = None
    type: TransactionType | None = None
    category_id: int | None = None


def validate_date_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise BusinessRuleError("date_from must be on or before date_to")


def apply_filters(query: Select, filters: TransactionFilters) -> Select:
    """Shared by the transaction list and the analytics queries so they always agree."""
    validate_date_range(filters.date_from, filters.date_to)
    if filters.date_from is not None:
        query = query.where(Transaction.occurred_on >= filters.date_from)
    if filters.date_to is not None:
        query = query.where(Transaction.occurred_on <= filters.date_to)
    if filters.type is not None:
        query = query.where(Transaction.type == filters.type)
    if filters.category_id is not None:
        query = query.where(Transaction.category_id == filters.category_id)
    return query


def list_transactions(
    db: Session, filters: TransactionFilters, limit: int, offset: int
) -> tuple[list[Transaction], int]:
    total = db.scalar(apply_filters(select(func.count(Transaction.id)), filters)) or 0
    query = (
        apply_filters(select(Transaction), filters)
        .options(joinedload(Transaction.category))
        .order_by(Transaction.occurred_on.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query)), total


def get_transaction(db: Session, transaction_id: int) -> Transaction:
    transaction = db.get(Transaction, transaction_id, options=[joinedload(Transaction.category)])
    if transaction is None:
        raise NotFoundError(f"Transaction {transaction_id} not found")
    return transaction


def create_transaction(db: Session, data: TransactionCreate) -> Transaction:
    _check_category(db, data.category_id, data.type)
    transaction = Transaction(**data.model_dump())
    db.add(transaction)
    db.commit()
    return get_transaction(db, transaction.id)


def update_transaction(db: Session, transaction_id: int, data: TransactionUpdate) -> Transaction:
    transaction = get_transaction(db, transaction_id)
    _check_category(db, data.category_id, data.type)
    for field, value in data.model_dump().items():
        setattr(transaction, field, value)
    db.commit()
    db.refresh(transaction)
    return transaction


def delete_transaction(db: Session, transaction_id: int) -> None:
    transaction = get_transaction(db, transaction_id)
    db.delete(transaction)
    db.commit()


def _check_category(db: Session, category_id: int, type_: TransactionType) -> None:
    category = db.get(Category, category_id)
    if category is None:
        raise BusinessRuleError(f"Category {category_id} does not exist")
    if category.type != type_:
        raise BusinessRuleError(
            f"Category '{category.name}' is for {category.type}, not {type_} transactions"
        )
