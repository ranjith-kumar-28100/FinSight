"""Anomalies endpoint — flagged transactions within an optional date range."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends

from backend.dependencies import get_repo
from backend.routers.transactions import _to_out
from backend.schemas import TransactionsResponse
from backend.db.repository import TransactionRepository

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", response_model=TransactionsResponse)
def list_flagged(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: TransactionRepository = Depends(get_repo),
) -> TransactionsResponse:
    rows = repo.get_transactions(
        needs_review=True, start_date=start, end_date=end,
    )
    return TransactionsResponse(transactions=[_to_out(t) for t in rows], count=len(rows))
