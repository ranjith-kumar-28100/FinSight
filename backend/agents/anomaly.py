"""Anomaly Detection Agent — flags unusual spending for human review.

Detection rules (applied per category per month):
  1. IQR rule:  amount > Q3 + 1.5 × IQR for that category's transaction amounts
  2. First-time: transaction in a category that has never appeared before this month
  3. Spike:  monthly total for a category is > 2.5× its trailing average

Flagged transactions get needs_review = True.
A lightweight LLM call generates a one-sentence explanation per anomaly batch.
"""

import json
import logging
from collections import defaultdict
from decimal import Decimal
from statistics import median

from openai import AzureOpenAI

from backend.config import AzureOpenAIConfig
from backend.db.repository import TransactionRepository

logger = logging.getLogger(__name__)


def run_anomaly_detection(
    repo: TransactionRepository,
    config: AzureOpenAIConfig,
) -> dict:
    """
    Detect anomalies and flag them in the database.

    Returns {flagged: int, anomalies: list[dict]}
    """
    txns = repo.get_transactions_for_anomaly()
    if not txns:
        return {"flagged": 0, "anomalies": []}

    # Group: category → month → [transactions]
    cat_month: dict[str, dict[str, list[dict]]
                    ] = defaultdict(lambda: defaultdict(list))
    for t in txns:
        month = t["date"][:7]  # YYYY-MM
        cat_month[t["category"]][month].append(t)

    # Discover categories that appear per month (for first-time detection)
    cat_first_month: dict[str, str] = {}
    for cat, months in cat_month.items():
        cat_first_month[cat] = min(months.keys())

    flagged_ids: list[str] = []
    anomaly_notes: list[dict] = []

    for cat, months in cat_month.items():
        all_amounts = [t["amount"]
                       for m_txns in months.values() for t in m_txns]
        q1, q3 = _quartiles(all_amounts)
        iqr = q3 - q1
        iqr_upper = q3 + Decimal("1.5") * iqr

        # Monthly totals for spike detection
        monthly_totals = {m: sum(t["amount"] for t in m_txns)
                          for m, m_txns in months.items()}
        sorted_months = sorted(monthly_totals.keys())

        for m_idx, month in enumerate(sorted_months):
            m_txns = months[month]
            m_total = monthly_totals[month]

            # Trailing average (all prior months)
            prior = [monthly_totals[pm] for pm in sorted_months[:m_idx]]
            trailing_avg = sum(prior) / len(prior) if prior else m_total

            # Rule 3: monthly spike
            if prior and trailing_avg > 0 and m_total > trailing_avg * Decimal("2.5"):
                for t in m_txns:
                    if t["txn_id"] not in flagged_ids:
                        flagged_ids.append(t["txn_id"])
                        anomaly_notes.append({
                            "txn_id": t["txn_id"],
                            "reason": f"{cat} spend ₹{m_total:.0f} this month is "
                            f"{float(m_total/trailing_avg):.1f}× the trailing average.",
                        })

            for t in m_txns:
                # Rule 1: IQR outlier
                if iqr_upper > 0 and t["amount"] > iqr_upper:
                    if t["txn_id"] not in flagged_ids:
                        flagged_ids.append(t["txn_id"])
                        anomaly_notes.append({
                            "txn_id": t["txn_id"],
                            "reason": f"₹{t['amount']:.0f} to {t['counterparty']} is unusually "
                            f"high for {cat} (IQR upper={iqr_upper:.0f}).",
                        })

                # Rule 2: first-time category this month
                if month == cat_first_month[cat] and m_idx == 0:
                    if t["txn_id"] not in flagged_ids:
                        flagged_ids.append(t["txn_id"])
                        anomaly_notes.append({
                            "txn_id": t["txn_id"],
                            "reason": f"First time spending in '{cat}' category.",
                        })

    if flagged_ids:
        repo.flag_anomalies(flagged_ids)
        logger.info("Anomaly detection: flagged %d transactions.",
                    len(flagged_ids))

    return {"flagged": len(flagged_ids), "anomalies": anomaly_notes}


def _quartiles(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Return (Q1, Q3) for a list of Decimal values."""
    if not values:
        return Decimal("0"), Decimal("0")
    sorted_v = sorted(values)
    n = len(sorted_v)
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    return sorted_v[q1_idx], sorted_v[min(q3_idx, n - 1)]
