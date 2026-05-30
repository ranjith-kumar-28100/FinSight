"""Reconciliation Agent — joins the three statements into one ledger.

The HDFC bank statement is the **backbone** (the real account: every debit/credit
with a running balance). GPay and Paytm are app-level views of the UPI subset of
that ledger. Each UPI payment carries the same NPCI **RRN** in all three exports,
just formatted differently:

    HDFC  Chq./Ref.No.    : "0000600199803992"   (zero-padded)
    Paytm UPI Ref No.     : 600199803992
    GPay  UPITransactionID: 600199803992

``ingestion._norm_ref`` strips that to a bare digit string, so the join is exact.

Two tiers:
  1. **Deterministic (RRN):** wallet row whose normalised ``source_ref`` equals a
     bank row's ``source_ref`` is the same payment — link with confidence 1.0.
  2. **Fuzzy fallback:** for wallet rows with no RRN match (format quirks, missing
     ref), match on amount + direction + date window + merchant/VPA similarity.

When linked, the bank row is enriched with the wallet's *clean* merchant name,
counterparty VPA, the user's own category tag (Paytm), and — when the bank row is
weakly categorised — the wallet's category. GPay and Paytm are disjoint (a payment
goes through one app), so a bank row links to at most one wallet row.

No LLM — pure rule-based.
"""

import logging
from datetime import timedelta
from difflib import SequenceMatcher

from backend.db.repository import TransactionRepository
from backend.models.transaction import Transaction

logger = logging.getLogger(__name__)

FUZZY_AUTO_THRESHOLD = 0.85
FUZZY_REVIEW_THRESHOLD = 0.55
DATE_WINDOW_DAYS = 3
_WEAK_CATEGORIES = {"", "Other", "Uncategorised"}


def run_reconciliation(repo: TransactionRepository) -> dict:
    """Join wallet rows onto the bank backbone and enrich the bank rows.

    Returns counts: ``{auto_linked, rrn_linked, fuzzy_linked, enriched,
    queued_for_review, orphan_wallet}``.
    """
    bank = repo.get_unlinked_by_source("bank")
    wallet = (
        repo.get_unlinked_by_source("gpay")
        + repo.get_unlinked_by_source("paytm")
    )

    if not bank or not wallet:
        logger.info(
            "Reconciliation: bank=%d wallet=%d — nothing to do.",
            len(bank), len(wallet),
        )
        return _summary(0, 0, 0, 0, len(wallet))

    linked_bank_ids: set[str] = set()
    rrn_linked = fuzzy_linked = enriched = queued = 0

    # -- Tier 1: deterministic RRN join -----------------------------------
    bank_by_ref: dict[str, Transaction] = {}
    for b in bank:
        if b.source_ref:  # empty for non-UPI rows (NACH/EMI/card)
            bank_by_ref.setdefault(b.source_ref, b)

    remaining_wallet: list[Transaction] = []
    for w in wallet:
        bank_txn = bank_by_ref.get(w.source_ref) if w.source_ref else None
        if bank_txn is not None and bank_txn.txn_id not in linked_bank_ids:
            repo.link_transactions(bank_txn.txn_id, w.txn_id, 1.0)
            _enrich(repo, bank_txn, w)
            linked_bank_ids.add(bank_txn.txn_id)
            rrn_linked += 1
            enriched += 1
        else:
            remaining_wallet.append(w)

    # -- Tier 2: fuzzy fallback (amount + direction + date + merchant) -----
    bank_by_date: dict[str, list[Transaction]] = {}
    for b in bank:
        if b.txn_id not in linked_bank_ids:
            bank_by_date.setdefault(b.date.isoformat(), []).append(b)

    for w in remaining_wallet:
        best, best_score = None, 0.0
        for delta in range(-DATE_WINDOW_DAYS, DATE_WINDOW_DAYS + 1):
            day = (w.date + timedelta(days=delta)).isoformat()
            for b in bank_by_date.get(day, []):
                if b.txn_id in linked_bank_ids:
                    continue
                if b.amount != w.amount or b.direction != w.direction:
                    continue
                score = _fuzzy_score(b, w, abs(delta))
                if score > best_score:
                    best, best_score = b, score

        if best is not None and best_score >= FUZZY_AUTO_THRESHOLD:
            repo.link_transactions(best.txn_id, w.txn_id, best_score)
            _enrich(repo, best, w)
            linked_bank_ids.add(best.txn_id)
            fuzzy_linked += 1
            enriched += 1
        elif best is not None and best_score >= FUZZY_REVIEW_THRESHOLD:
            repo.flag_anomalies([w.txn_id])
            queued += 1

    orphan = len(wallet) - rrn_linked - fuzzy_linked
    logger.info(
        "Reconciliation: rrn=%d fuzzy=%d enriched=%d queued=%d orphan=%d",
        rrn_linked, fuzzy_linked, enriched, queued, orphan,
    )
    return _summary(rrn_linked, fuzzy_linked, enriched, queued, orphan)


def _enrich(repo: TransactionRepository, bank: Transaction, wallet: Transaction) -> None:
    """Copy the wallet's cleaner context onto its bank backbone row."""
    category = subcategory = None
    # Adopt the wallet's category only when the bank row is weakly categorised —
    # "Paid to JMMART" (wallet) categorises far better than "UPI-JMMART-..." (bank).
    if bank.category in _WEAK_CATEGORIES and wallet.category not in _WEAK_CATEGORIES:
        category, subcategory = wallet.category, wallet.subcategory
    repo.enrich_bank_row(
        bank.txn_id,
        enriched_counterparty=wallet.counterparty or None,
        upi_id=wallet.upi_id,
        counterparty_app=wallet.counterparty_app,
        external_tag=wallet.external_tag,
        category=category,
        subcategory=subcategory,
    )


def _fuzzy_score(bank: Transaction, wallet: Transaction, day_delta: int) -> float:
    """Likelihood a bank row and wallet row are the same payment (0–1).

    Amount + direction are already equal before this is called.
    """
    score = 0.50
    score += max(0.0, 0.20 - day_delta * 0.07)  # date proximity

    # VPA match is the strongest soft signal short of the RRN itself.
    if bank.upi_id and wallet.upi_id and bank.upi_id.lower() == wallet.upi_id.lower():
        score += 0.30
    else:
        score += 0.30 * _name_similarity(bank, wallet)

    return min(score, 1.0)


def _name_similarity(bank: Transaction, wallet: Transaction) -> float:
    """Fuzzy similarity between the wallet merchant and the bank narration."""
    name = (wallet.counterparty or "").lower().replace(" ", "")
    if not name:
        return 0.0
    narration = (bank.raw_description or "").lower().replace(" ", "")
    if name in narration:
        return 1.0
    return SequenceMatcher(None, name, narration).ratio()


def _summary(rrn: int, fuzzy: int, enriched: int, queued: int, orphan: int) -> dict:
    return {
        "auto_linked": rrn + fuzzy,
        "rrn_linked": rrn,
        "fuzzy_linked": fuzzy,
        "enriched": enriched,
        "queued_for_review": queued,
        "orphan_wallet": orphan,
    }


def backfill_enrichment(repo: TransactionRepository) -> int:
    """Populate enriched_counterparty for bank rows already linked to a wallet row.

    Idempotent — only writes when the bank row is still missing an enriched name.
    """
    bank_rows = [
        t for t in repo.get_transactions(bank_only=True)
        if not t.enriched_counterparty
    ]
    filled = 0
    for bank_txn in bank_rows:
        for w in repo.get_wallet_detail_for_bank(bank_txn.txn_id):
            if w.counterparty:
                _enrich(repo, bank_txn, w)
                filled += 1
                break
    if filled:
        logger.info("Back-filled enrichment on %d bank rows.", filled)
    return filled
