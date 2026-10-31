from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import TransactionType
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.common import ErrorResponse
from app.services import categories as service

router = APIRouter(prefix="/categories", tags=["categories"])

DbSession = Annotated[Session, Depends(get_db)]
NOT_FOUND = {404: {"model": ErrorResponse}}
CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=list[CategoryRead])
def list_categories(
    db: DbSession, type_: Annotated[TransactionType | None, Query(alias="type")] = None
):
    return service.list_categories(db, type_)


@router.post(
    "", response_model=CategoryRead, status_code=status.HTTP_201_CREATED, responses=CONFLICT
)
def create_category(data: CategoryCreate, db: DbSession):
    return service.create_category(db, data)


@router.get("/{category_id}", response_model=CategoryRead, responses=NOT_FOUND)
def get_category(category_id: int, db: DbSession):
    return service.get_category(db, category_id)


@router.patch("/{category_id}", response_model=CategoryRead, responses={**NOT_FOUND, **CONFLICT})
def update_category(category_id: int, data: CategoryUpdate, db: DbSession):
    return service.update_category(db, category_id, data)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **CONFLICT},
)
def delete_category(category_id: int, db: DbSession) -> None:
    service.delete_category(db, category_id)
