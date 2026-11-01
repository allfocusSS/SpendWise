from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import UNAUTHORIZED, CurrentUser, DbSession
from app.models import TransactionType
from app.schemas.common import ErrorResponse
from app.schemas.transaction import (
    TransactionCreate,
    TransactionList,
    TransactionRead,
    TransactionUpdate,
)
from app.services import transactions as service
from app.services.transactions import TransactionFilters

# Every route needs a signed-in user and only sees that user's transactions.
router = APIRouter(prefix="/transactions", tags=["transactions"], responses=UNAUTHORIZED)
NOT_FOUND = {404: {"model": ErrorResponse}}


@router.get("", response_model=TransactionList)
def list_transactions(
    db: DbSession,
    user: CurrentUser,
    date_from: date | None = None,
    date_to: date | None = None,
    type_: Annotated[TransactionType | None, Query(alias="type")] = None,
    category_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = TransactionFilters(
        user_id=user.id, date_from=date_from, date_to=date_to, type=type_, category_id=category_id
    )
    items, total = service.list_transactions(db, filters, limit, offset)
    return TransactionList(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(data: TransactionCreate, db: DbSession, user: CurrentUser):
    return service.create_transaction(db, user.id, data)


@router.get("/{transaction_id}", response_model=TransactionRead, responses=NOT_FOUND)
def get_transaction(transaction_id: int, db: DbSession, user: CurrentUser):
    return service.get_transaction(db, user.id, transaction_id)


@router.put("/{transaction_id}", response_model=TransactionRead, responses=NOT_FOUND)
def update_transaction(
    transaction_id: int, data: TransactionUpdate, db: DbSession, user: CurrentUser
):
    return service.update_transaction(db, user.id, transaction_id, data)


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
def delete_transaction(transaction_id: int, db: DbSession, user: CurrentUser) -> None:
    service.delete_transaction(db, user.id, transaction_id)
