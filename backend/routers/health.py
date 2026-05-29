"""Health + DB stats endpoint."""

from fastapi import APIRouter, Depends

from backend.dependencies import get_repo
from backend.schemas import HealthResponse
from backend.db.repository import TransactionRepository

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(repo: TransactionRepository = Depends(get_repo)) -> HealthResponse:
    stats = repo.get_enrichment_stats()
    min_d, max_d = repo.get_date_range()
    return HealthResponse(
        status="ok",
        bank_transactions=stats["bank_total"],
        enriched=stats["enriched"],
        enriched_pct=stats["enriched_pct"],
        orphan_wallet=stats["orphan_wallet"],
        data_min_date=min_d,
        data_max_date=max_d,
    )
