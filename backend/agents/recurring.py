"""Recurring Detection Agent — identifies EMIs, SIPs, subscriptions, etc.

Algorithm:
  1. Group debit transactions by normalised counterparty name.
  2. For groups with ≥ 2 occurrences, compute median inter-arrival gap.
  3. If median gap ≈ 30 days → monthly cadence; ≈ 7 days → weekly.
  4. Check amount variance: std/mean < 10% → fixed amount.
  5. Classify series type from counterparty/category keywords.
  6. Mark transactions as recurring in the DB and store series metadata.

No LLM needed — pure deterministic clustering.
"""

import logging
import re
import uuid
from collections import defaultdict
from decimal import Decimal
from statistics import median, stdev

from backend.db.repository import TransactionRepository
from backend.models.transaction import TransactionDirection

logger = logging.getLogger(__name__)

# Cadence tolerances (in days)
MONTHLY_MIN, MONTHLY_MAX = 25, 35
WEEKLY_MIN, WEEKLY_MAX = 5, 9

# Keyword patterns for series classification (checked against counterparty + category)
_SERIES_RULES: list[tuple[str, str]] = [
    # (regex pattern, recurring_type)
    (r'\b(emi|loan|credit\s*card\s*due|repay|bajaj|hdfc\s*ltd|icici\s*home|hl|cl|pl)\b', "emi"),
    (r'\b(sip|mutual\s*fund|zerodha|groww|kuvera|coin|angel\s*one|nps|ppf|invest)\b', "sip"),
    (r'\b(netflix|hotstar|spotify|prime|youtube|disney|sony\s*liv|zee5|crunchyroll|apple|google\s*one|microsoft|adobe)\b', "subscription"),
    (r'\b(lic|insurance|icici\s*prud|hdfc\s*life|tata\s*aig|star\s*health|policy)\b', "insurance"),
    (r'\b(rent|rental|landlord|owner|society|maintenance|housing)\b', "rent"),
    (r'\b(electricity|bescom|tpddl|bses|jio|airtel|vodafone|broadband|internet|act\s*fibernet|tatasky|gas\s*bill|water\s*bill|recharge|mobile\s*bill)\b', "utility"),
]


def run_recurring_detection(repo: TransactionRepository) -> dict:
    """
    Detect recurring payment series and update the database.

    Returns summary: {series_found, transactions_marked}
    """
    # Fetch bank debits only — wallet rows are enrichment, never counted.
    all_txns = repo.get_transactions(direction="debit", bank_only=True)
    if not all_txns:
        return {"series_found": 0, "transactions_marked": 0}

    # Group by normalised merchant name (prefer the enriched name when available).
    groups: dict[str, list] = defaultdict(list)
    for t in all_txns:
        merchant = t.enriched_counterparty or t.counterparty or t.raw_description
        key = _normalise(merchant)
        if key:
            groups[key].append(t)

    series_list: list[dict] = []
    all_txn_ids_to_mark: list[tuple[list[str], str | None]] = []

    for cp_key, txns in groups.items():
        if len(txns) < 2:
            continue

        txns_sorted = sorted(txns, key=lambda t: t.date)
        dates = [t.date for t in txns_sorted]
        amounts = [float(t.amount) for t in txns_sorted]

        # Compute inter-arrival gaps in days
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        if not gaps:
            continue
        med_gap = median(gaps)

        # Determine cadence
        if MONTHLY_MIN <= med_gap <= MONTHLY_MAX:
            cadence = "monthly"
        elif WEEKLY_MIN <= med_gap <= WEEKLY_MAX:
            cadence = "weekly"
        else:
            continue  # Irregular — not recurring

        # Amount consistency
        avg_amount = sum(amounts) / len(amounts)
        amount_std = stdev(amounts) if len(amounts) > 1 else 0.0
        if avg_amount > 0 and amount_std / avg_amount > 0.15:
            continue  # Too variable to be a reliable series

        # Determine series type
        combined_text = (
            cp_key + " " + (txns_sorted[0].category or "") + " " +
            (txns_sorted[0].raw_description or "")
        ).lower()
        recurring_type = _classify_series(combined_text)

        series_id = str(uuid.uuid4())
        txn_ids = [t.txn_id for t in txns_sorted]

        head = txns_sorted[0]
        series_list.append({
            "series_id": series_id,
            "counterparty": head.enriched_counterparty or head.counterparty or cp_key,
            "category": head.category or "",
            "avg_amount": Decimal(str(round(avg_amount, 2))),
            "cadence": cadence,
            "recurring_type": recurring_type,
            "first_seen": dates[0].isoformat(),
            "last_seen": dates[-1].isoformat(),
            "txn_count": len(txns_sorted),
        })
        all_txn_ids_to_mark.append((txn_ids, recurring_type))

    if series_list:
        repo.insert_recurring_series(series_list)

    total_marked = 0
    for txn_ids, rtype in all_txn_ids_to_mark:
        total_marked += repo.mark_recurring(txn_ids, rtype)

    logger.info(
        "Recurring detection: %d series found, %d transactions marked.",
        len(series_list), total_marked,
    )
    return {"series_found": len(series_list), "transactions_marked": total_marked}


def _normalise(text: str) -> str:
    """Normalise a counterparty/description for grouping."""
    if not text:
        return ""
    # Lowercase, strip VPA suffixes (@xxx), remove special chars
    text = text.lower()
    text = re.sub(r'@\w+', '', text)         # Remove VPA domain
    text = re.sub(r'\d{6,}', '', text)       # Remove long ref numbers
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Keep only the first 4 words for grouping (avoid one-off descriptions)
    words = text.split()
    return " ".join(words[:4]) if words else ""


def _classify_series(text: str) -> str | None:
    """Return the recurring_type based on keyword matching."""
    for pattern, rtype in _SERIES_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return rtype
    return None
