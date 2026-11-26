from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import UNAUTHORIZED, CurrentUser, DbSession
from app.models import TransactionType
from app.schemas.analytics import CategoryBreakdown, MonthlyTrend, Summary
from app.services import analytics as service

# Every figure is calculated from the signed-in user's transactions only.
router = APIRouter(prefix="/analytics", tags=["analytics"], responses=UNAUTHORIZED)


@router.get("/summary", response_model=Summary, response_model_exclude_unset=True)
def get_summary(
    db: DbSession,
    user: CurrentUser,
    date_from: Annotated[
        date | None, Query(description="First day to include (inclusive).")
    ] = None,
    date_to: Annotated[date | None, Query(description="Last day to include (inclusive).")] = None,
    include_monthly: Annotated[
        bool,
        Query(
            description=(
                "Include monthly_breakdown from the same rows as the totals, for up to 24 months. "
                "An open bound uses the first or last matching transaction month. A wider span "
                "returns null; an open range without transactions returns an empty list."
            )
        ),
    ] = False,
):
    """Total income, expenses and balance. Without dates this is the all-time balance."""
    return service.get_summary(db, user.id, date_from, date_to, include_monthly=include_monthly)


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
    months: Annotated[int, Query(ge=1, le=service.MAX_MONTHS)] = 6,
    until: Annotated[
        date | None,
        Query(
            description=(
                "Any date in the last full month to show (0001-01-01 through 9999-12-31). "
                "Windows reaching back before January 0001 start in January 0001."
            )
        ),
    ] = None,
):
    return service.get_monthly_trend(db, user.id, months, until)
