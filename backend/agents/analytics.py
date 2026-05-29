"""Analytics Agent — computes the monthly money map.

Per month:
  income            = SUM of credit transactions (excl. pure wallet-to-wallet transfers)
  total_spend       = SUM of debit transactions
  fixed_obligations = SUM of debits where is_recurring = 1
  discretionary     = total_spend - fixed_obligations
  net_savings       = income - total_spend
  savings_rate      = net_savings / income  (0.0 if income == 0)

All arithmetic uses Python Decimal. The LLM never touches money totals.
"""

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from backend.db.repository import TransactionRepository
from backend.models.transaction import Transaction, TransactionDirection

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _bucket_to_maps(transactions: list[Transaction]) -> list[dict]:
    """Bucket bank transactions by YYYY-MM into the monthly-map shape.

    Pure function — does not persist anything. Used by both `run_analytics`
    (which persists to monthly_maps) and `compute_monthly_maps_in_range`
    (which returns ephemeral results for UI date filtering)."""
    monthly_credits: dict[str, Decimal] = defaultdict(Decimal)
    monthly_debits: dict[str, Decimal] = defaultdict(Decimal)
    monthly_fixed: dict[str, Decimal] = defaultdict(Decimal)

    for t in transactions:
        month_key = t.date.strftime("%Y-%m")
        if t.direction == TransactionDirection.CREDIT:
            monthly_credits[month_key] += t.amount
        else:
            monthly_debits[month_key] += t.amount
            if t.is_recurring:
                monthly_fixed[month_key] += t.amount

    all_months = sorted(
        set(list(monthly_credits.keys()) + list(monthly_debits.keys())))
    maps: list[dict] = []
    for month in all_months:
        income = monthly_credits[month].quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP)
        total_spend = monthly_debits[month].quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP)
        fixed = monthly_fixed[month].quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP)
        discretionary = (
            total_spend - fixed).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        net_savings = (income - total_spend).quantize(TWO_PLACES,
                                                      rounding=ROUND_HALF_UP)
        savings_rate = (
            (net_savings / income).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if income > 0 else Decimal("0")
        )
        maps.append({
            "month": month,
            "income": income,
            "total_spend": total_spend,
            "fixed_obligations": fixed,
            "discretionary": discretionary,
            "net_savings": net_savings,
            "savings_rate": savings_rate,
        })
    return maps


def run_analytics(repo: TransactionRepository) -> dict:
    """Compute monthly money maps over ALL bank rows and persist them.

    Returns summary: {months_computed: int, maps: list[dict]}
    """
    all_txns = repo.get_transactions(bank_only=True)
    if not all_txns:
        return {"months_computed": 0, "maps": []}

    maps = _bucket_to_maps(all_txns)
    for m in maps:
        repo.upsert_monthly_map(
            m["month"], m["income"], m["total_spend"], m["fixed_obligations"],
            m["discretionary"], m["net_savings"], m["savings_rate"],
        )
    logger.info("Analytics: computed money maps for %d months.", len(maps))
    return {"months_computed": len(maps), "maps": maps}


def compute_monthly_maps_in_range(
    repo: TransactionRepository,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict]:
    """Compute monthly maps for transactions in a date range, without persisting.

    Used by the UI when the user picks a sub-range so every tab reflects only
    the filtered transactions. Returns the same shape as `run_analytics`'s maps.
    """
    txns = repo.get_transactions(
        bank_only=True, start_date=start_date, end_date=end_date,
    )
    return _bucket_to_maps(txns)
