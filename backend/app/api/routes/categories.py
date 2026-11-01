from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import UNAUTHORIZED, CurrentUser, DbSession
from app.models import TransactionType
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.common import ErrorResponse
from app.services import categories as service

# Every route needs a signed-in user and only sees that user's categories.
router = APIRouter(prefix="/categories", tags=["categories"], responses=UNAUTHORIZED)

NOT_FOUND = {404: {"model": ErrorResponse}}
CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=list[CategoryRead])
def list_categories(
    db: DbSession,
    user: CurrentUser,
    type_: Annotated[TransactionType | None, Query(alias="type")] = None,
):
    return service.list_categories(db, user.id, type_)


@router.post(
    "", response_model=CategoryRead, status_code=status.HTTP_201_CREATED, responses=CONFLICT
)
def create_category(data: CategoryCreate, db: DbSession, user: CurrentUser):
    return service.create_category(db, user.id, data)


@router.get("/{category_id}", response_model=CategoryRead, responses=NOT_FOUND)
def get_category(category_id: int, db: DbSession, user: CurrentUser):
    return service.get_category(db, user.id, category_id)


@router.patch("/{category_id}", response_model=CategoryRead, responses={**NOT_FOUND, **CONFLICT})
def update_category(category_id: int, data: CategoryUpdate, db: DbSession, user: CurrentUser):
    return service.update_category(db, user.id, category_id, data)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**NOT_FOUND, **CONFLICT},
)
def delete_category(category_id: int, db: DbSession, user: CurrentUser) -> None:
    service.delete_category(db, user.id, category_id)
