"""Reconciliation Agent — links wallet records to the HDFC bank record they
mirror, and enriches the bank record with the cleaner wallet merchant name.

The bank statement is the source of truth for amounts and dates. GPay/Paytm
records exist only to add merchant context — a single UPI payment shows up in
the HDFC statement as a cryptic narration (e.g.
``UPI-ZEPTO MARKETPLACE PR-...PAYU@MAIRTEL``) and on GPay as ``PaidToZepto``.
Reconciliation finds the pair, links them, and writes the GPay merchant name
into the bank row's ``enriched_counterparty`` column so the UI can show
"Zepto" instead of the noisy narration.

Strategy (driven from the bank side):
  For each unlinked bank debit, scan unlinked wallet debits within ±2 days
  with the same amount. Score by UPI-ref overlap and date proximity. Matches
  with score ≥ 0.85 are auto-linked + enriched. 0.50–0.84 flagged for review.

No LLM — pure rule-based fuzzy matching.
"""

import logging
from datetime import timedelta

from backend.db.repository import TransactionRepository
from backend.models.transaction import Transaction, TransactionDirection

logger = logging.getLogger(__name__)

HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.50
DATE_WINDOW_DAYS = 2


def run_reconciliation(repo: TransactionRepository) -> dict:
    """Reconcile bank debits against wallet (GPay/Paytm) debits.

    Returns ``{auto_linked, enriched, queued_for_review, orphan_wallet}``.
    """
    bank_debits = [
        t for t in repo.get_unlinked_by_source("bank")
        if t.direction == TransactionDirection.DEBIT
    ]
    wallet_debits = [
        t for t in repo.get_unlinked_by_source("gpay") + repo.get_unlinked_by_source("paytm")
        if t.direction == TransactionDirection.DEBIT
    ]

    if not bank_debits or not wallet_debits:
        logger.info(
            "Reconciliation: bank_debits=%d wallet_debits=%d — nothing to do.",
            len(bank_debits), len(wallet_debits),
        )
        return {
            "auto_linked": 0,
            "enriched": 0,
            "queued_for_review": 0,
            "orphan_wallet": len(wallet_debits),
        }

    # Index wallet debits by date for O(1) window scans.
    wallet_by_date: dict[str, list[Transaction]] = {}
    for w in wallet_debits:
        wallet_by_date.setdefault(w.date.isoformat(), []).append(w)

    claimed_wallet_ids: set[str] = set()
    auto_linked = 0
    enriched = 0
    queued = 0

    for bank_txn in bank_debits:
        candidates: list[tuple[Transaction, float]] = []
        for delta in range(-DATE_WINDOW_DAYS, DATE_WINDOW_DAYS + 1):
            check_date = (bank_txn.date + timedelta(days=delta)).isoformat()
            for wallet_txn in wallet_by_date.get(check_date, []):
                if wallet_txn.txn_id in claimed_wallet_ids:
                    continue
                if wallet_txn.amount != bank_txn.amount:
                    continue
                score = _match_score(bank_txn, wallet_txn, abs(delta))
                candidates.append((wallet_txn, score))

        if not candidates:
            continue

        best_wallet, best_score = max(candidates, key=lambda x: x[1])

        if best_score >= HIGH_CONFIDENCE_THRESHOLD:
            repo.link_transactions(
                bank_txn.txn_id, best_wallet.txn_id, best_score)
            claimed_wallet_ids.add(best_wallet.txn_id)
            auto_linked += 1
            if best_wallet.counterparty:
                repo.update_enriched_counterparty(
                    bank_txn.txn_id, best_wallet.counterparty)
                enriched += 1
        elif best_score >= MEDIUM_CONFIDENCE_THRESHOLD:
            repo.flag_anomalies([bank_txn.txn_id, best_wallet.txn_id])
            queued += 1

    orphan_wallet = len(wallet_debits) - auto_linked
    logger.info(
        "Reconciliation complete: auto_linked=%d enriched=%d queued=%d orphan_wallet=%d",
        auto_linked, enriched, queued, orphan_wallet,
    )
    return {
        "auto_linked": auto_linked,
        "enriched": enriched,
        "queued_for_review": queued,
        "orphan_wallet": orphan_wallet,
    }


def _match_score(bank: Transaction, wallet: Transaction, day_delta: int) -> float:
    """Score how likely a bank debit and a wallet debit represent the same UPI payment (0–1)."""
    score = 0.40  # amount already matched

    # Date proximity bonus
    score += max(0.0, 0.30 - day_delta * 0.10)

    # UPI reference overlap: wallet stores the full UPI Transaction ID;
    # HDFC narration carries it as part of the Chq./Ref.No. field.
    wallet_ref = wallet.source_ref.strip()
    bank_ref = bank.source_ref.strip()
    bank_narration = bank.raw_description or ""
    if wallet_ref:
        if (bank_ref and (wallet_ref in bank_ref or bank_ref in wallet_ref)) or (
            wallet_ref in bank_narration
        ):
            score += 0.30

    # Counterparty similarity bonus: prefix of the wallet's clean name appears
    # in the bank narration.
    wallet_cp = (wallet.counterparty or "").lower().replace(" ", "")
    bank_narr_norm = bank_narration.lower().replace(" ", "")
    if wallet_cp and len(wallet_cp) > 3 and wallet_cp[:8] in bank_narr_norm:
        score += 0.10

    return min(score, 1.0)


def backfill_enrichment(repo: TransactionRepository) -> int:
    """Populate enriched_counterparty for bank rows already linked to a wallet row.

    Run once on existing databases where reconciliation linked rows under the
    old (non-enriching) flow. Idempotent — only writes when the bank row is
    still missing an enriched name.
    """
    bank_rows = [t for t in repo.get_transactions(
        bank_only=True) if not t.enriched_counterparty]
    if not bank_rows:
        return 0

    filled = 0
    for bank_txn in bank_rows:
        wallet_rows = repo.get_wallet_detail_for_bank(bank_txn.txn_id)
        for w in wallet_rows:
            if w.counterparty:
                repo.update_enriched_counterparty(
                    bank_txn.txn_id, w.counterparty)
                filled += 1
                break
    if filled:
        logger.info(
            "Back-filled enriched_counterparty on %d existing bank rows.", filled)
    return filled
