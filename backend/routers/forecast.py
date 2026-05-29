"""Forecast endpoint — projects N months forward from a filtered baseline."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.dependencies import get_repo
from backend.schemas import ForecastProjection, ForecastResponse, MonthlyMap
from backend.agents.analytics import compute_monthly_maps_in_range
from backend.agents.forecast import run_forecast
from backend.db.repository import TransactionRepository

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("", response_model=ForecastResponse)
def forecast(
    horizon: int = Query(default=3, ge=1, le=12),
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: TransactionRepository = Depends(get_repo),
) -> ForecastResponse:
    history = [
        MonthlyMap(**m) for m in compute_monthly_maps_in_range(repo, start, end)
    ]
    projections = [
        ForecastProjection(**p)
        for p in run_forecast(repo, horizon=horizon, start_date=start, end_date=end)
    ]
    return ForecastResponse(history=history, projections=projections)
