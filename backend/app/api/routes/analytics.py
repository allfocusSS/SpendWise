from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import UNAUTHORIZED, CurrentUser, DbSession
from app.models import TransactionType
from app.schemas.analytics import CategoryBreakdown, MonthlyTrend, Summary
from app.services import analytics as service

# Every figure is calculated from the signed-in user's transactions only.
router = APIRouter(prefix="/analytics", tags=["analytics"], responses=UNAUTHORIZED)


@router.get("/summary", response_model=Summary)
def get_summary(
    db: DbSession, user: CurrentUser, date_from: date | None = None, date_to: date | None = None
):
    """Total income, expenses and balance. Without dates this is the all-time balance."""
    return service.get_summary(db, user.id, date_from, date_to)


@router.get("/by-category", response_model=CategoryBreakdown)
def get_category_breakdown(
    db: DbSession,
    user: CurrentUser,
    type_: Annotated[TransactionType, Query(alias="type")] = TransactionType.EXPENSE,
    date_from: date | None = None,
    date_to: date | None = None,
):
    return service.get_category_breakdown(db, user.id, type_, date_from, date_to)


@router.get("/monthly-trend", response_model=MonthlyTrend)
def get_monthly_trend(
    db: DbSession,
    user: CurrentUser,
    months: Annotated[int, Query(ge=1, le=24)] = 6,
    until: Annotated[date | None, Query(description="Any date in the last month to show")] = None,
):
    return service.get_monthly_trend(db, user.id, months, until)
