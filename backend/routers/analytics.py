"""Analytics endpoints: totals, categories, top merchants, monthly maps, heatmap."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.dependencies import get_repo
from backend.schemas import (
    CategorySummary,
    IncomeExpense,
    InsightsResponse,
    MerchantSummary,
    MonthlyCategoryCell,
    MonthlyMap,
)
from backend.agents.analytics import compute_monthly_maps_in_range
from backend.db.repository import TransactionRepository

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/insights", response_model=InsightsResponse)
def insights(
    start: Optional[date] = None,
    end: Optional[date] = None,
    top_merchants: int = Query(default=10, le=50),
    repo: TransactionRepository = Depends(get_repo),
) -> InsightsResponse:
    totals_raw = repo.get_income_expense_totals(start, end)
    totals = IncomeExpense(
        income=totals_raw["income"],
        expense=totals_raw["expense"],
        net=totals_raw["income"] - totals_raw["expense"],
    )
    cats = [CategorySummary(**c) for c in repo.get_categories_summary(start, end)]
    merchants = [MerchantSummary(**m) for m in repo.get_top_counterparties(top_merchants, start, end)]
    maps = [MonthlyMap(**m) for m in compute_monthly_maps_in_range(repo, start, end)]
    return InsightsResponse(
        totals=totals, categories=cats, top_merchants=merchants, monthly_maps=maps,
    )


@router.get("/monthly-maps", response_model=list[MonthlyMap])
def monthly_maps(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: TransactionRepository = Depends(get_repo),
) -> list[MonthlyMap]:
    return [MonthlyMap(**m) for m in compute_monthly_maps_in_range(repo, start, end)]


@router.get("/category-heatmap", response_model=list[MonthlyCategoryCell])
def category_heatmap(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: TransactionRepository = Depends(get_repo),
) -> list[MonthlyCategoryCell]:
    return [
        MonthlyCategoryCell(**row)
        for row in repo.get_monthly_category_breakdown(start, end)
    ]
