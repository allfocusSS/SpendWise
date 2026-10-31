from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import TransactionType
from app.schemas.analytics import CategoryBreakdown, MonthlyTrend, Summary
from app.services import analytics as service

router = APIRouter(prefix="/analytics", tags=["analytics"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/summary", response_model=Summary)
def get_summary(db: DbSession, date_from: date | None = None, date_to: date | None = None):
    """Total income, expenses and balance. Without dates this is the all-time balance."""
    return service.get_summary(db, date_from, date_to)


@router.get("/by-category", response_model=CategoryBreakdown)
def get_category_breakdown(
    db: DbSession,
    type_: Annotated[TransactionType, Query(alias="type")] = TransactionType.EXPENSE,
    date_from: date | None = None,
    date_to: date | None = None,
):
    return service.get_category_breakdown(db, type_, date_from, date_to)


@router.get("/monthly-trend", response_model=MonthlyTrend)
def get_monthly_trend(
    db: DbSession,
    months: Annotated[int, Query(ge=1, le=24)] = 6,
    until: Annotated[date | None, Query(description="Any date in the last month to show")] = None,
):
    return service.get_monthly_trend(db, months, until)
