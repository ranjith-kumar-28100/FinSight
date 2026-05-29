"""Transactions list / wallet detail / label update."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.dependencies import get_repo
from backend.schemas import (
    TransactionOut,
    TransactionsResponse,
    UpdateLabelRequest,
)
from backend.db.repository import TransactionRepository
from backend.models.transaction import Transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _to_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        txn_id=t.txn_id,
        source=t.source.value,
        source_ref=t.source_ref,
        date=t.date,
        amount=t.amount,
        direction=t.direction.value,
        raw_description=t.raw_description,
        counterparty=t.counterparty,
        enriched_counterparty=t.enriched_counterparty,
        merchant=t.enriched_counterparty or t.counterparty,
        category=t.category,
        subcategory=t.subcategory,
        is_recurring=t.is_recurring,
        recurring_type=t.recurring_type,
        linked_txn_id=t.linked_txn_id,
        confidence=t.confidence,
        needs_review=t.needs_review,
        user_label=t.user_label,
    )


@router.get("", response_model=TransactionsResponse)
def list_transactions(
    start: Optional[date] = None,
    end: Optional[date] = None,
    category: Optional[str] = None,
    direction: Optional[str] = None,
    source: Optional[str] = None,
    needs_review: Optional[bool] = None,
    limit: int = Query(default=500, le=5000),
    repo: TransactionRepository = Depends(get_repo),
) -> TransactionsResponse:
    rows = repo.get_transactions(
        start_date=start, end_date=end, category=category,
        direction=direction, source=source, needs_review=needs_review,
    )[:limit]
    return TransactionsResponse(transactions=[_to_out(t) for t in rows], count=len(rows))


@router.get("/orphans", response_model=TransactionsResponse)
def orphan_wallet(
    repo: TransactionRepository = Depends(get_repo),
) -> TransactionsResponse:
    rows = repo.get_orphan_wallet_transactions()
    return TransactionsResponse(transactions=[_to_out(t) for t in rows], count=len(rows))


@router.get("/{bank_txn_id}/wallet-detail", response_model=TransactionsResponse)
def wallet_detail(
    bank_txn_id: str,
    repo: TransactionRepository = Depends(get_repo),
) -> TransactionsResponse:
    rows = repo.get_wallet_detail_for_bank(bank_txn_id)
    return TransactionsResponse(transactions=[_to_out(t) for t in rows], count=len(rows))


@router.patch("/{txn_id}/label")
def update_label(
    txn_id: str,
    body: UpdateLabelRequest,
    repo: TransactionRepository = Depends(get_repo),
) -> dict:
    ok = repo.update_user_label(txn_id, body.label)
    if not ok:
        raise HTTPException(404, "Transaction not found")
    return {"ok": True}
