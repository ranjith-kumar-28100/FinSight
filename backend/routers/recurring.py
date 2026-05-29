"""Recurring series endpoint."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends

from backend.dependencies import get_repo
from backend.schemas import RecurringSeries
from backend.db.repository import TransactionRepository

router = APIRouter(prefix="/recurring", tags=["recurring"])


@router.get("", response_model=list[RecurringSeries])
def list_series(
    start: Optional[date] = None,
    end: Optional[date] = None,
    repo: TransactionRepository = Depends(get_repo),
) -> list[RecurringSeries]:
    return [RecurringSeries(**s) for s in repo.get_recurring_series(start, end)]
