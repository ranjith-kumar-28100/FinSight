"""LangGraph Orchestrator — wires all agents into a stateful pipeline.

Graph topology:
  START → ingest → reconcile → categorise → detect_recurring
        → compute_analytics → detect_anomalies → END

State is persisted via LangGraph's MemorySaver so the Streamlit app can
inspect intermediate results and resume after human-in-loop interrupts.

Each node has a single responsibility; the bank (HDFC) statement is the
source of truth for amounts, and wallet (GPay/Paytm) records are used only
for enrichment and drill-down.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.anomaly import run_anomaly_detection
from backend.agents.analytics import run_analytics
from backend.agents.categorisation import (
    REVIEW_THRESHOLD,
    categorise_by_rules,
    categorise_by_tag,
)
from backend.agents.ingestion import parse_gpay, parse_hdfc, parse_paytm
from backend.agents.reconciliation import backfill_enrichment, run_reconciliation
from backend.agents.recurring import run_recurring_detection
from backend.config import AzureOpenAIConfig
from backend.db.repository import TransactionRepository
from backend.db.schema import init_db
from backend.llm.provider import LLMProvider
from backend.models.transaction import Transaction, TransactionSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class PipelineState(TypedDict):
    hdfc_path: Optional[str]
    gpay_path: Optional[str]
    paytm_path: Optional[str]
    db_path: str
    status: str          # current step name for UI progress
    errors: list[str]
    # Per-step result summaries (for UI)
    ingestion_summary: dict
    reconciliation_summary: dict
    categorisation_summary: dict
    recurring_summary: dict
    analytics_summary: dict
    anomaly_summary: dict


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

def _make_ingest_node(config: AzureOpenAIConfig):
    def ingest(state: PipelineState) -> PipelineState:
        db_path = Path(state["db_path"])
        init_db(db_path)
        repo = TransactionRepository(db_path)

        all_txns: list[Transaction] = []
        errors = list(state.get("errors", []))

        for source, path_key, parser in [
            ("HDFC", "hdfc_path", parse_hdfc),
            ("GPay", "gpay_path", parse_gpay),
            ("Paytm", "paytm_path", parse_paytm),
        ]:
            path_str = state.get(path_key)
            if not path_str:
                continue
            try:
                txns = parser(Path(path_str))
                all_txns.extend(txns)
                logger.info("Ingested %d transactions from %s.",
                            len(txns), source)
            except Exception as e:
                msg = f"{source} ingestion failed: {e}"
                errors.append(msg)
                logger.exception(msg)

        inserted = repo.insert_transactions(all_txns) if all_txns else 0

        return {
            **state,
            "status": "ingested",
            "errors": errors,
            "ingestion_summary": {
                "total_parsed": len(all_txns),
                "inserted": inserted,
            },
        }
    return ingest


def _make_reconcile_node():
    def reconcile(state: PipelineState) -> PipelineState:
        repo = TransactionRepository(Path(state["db_path"]))
        summary = run_reconciliation(repo)
        # Patch up legacy rows that were linked before enrichment write-back existed.
        backfilled = backfill_enrichment(repo)
        if backfilled:
            summary["enriched"] = summary.get("enriched", 0) + backfilled
            summary["backfilled"] = backfilled
        return {**state, "status": "reconciled", "reconciliation_summary": summary}
    return reconcile


def _make_categorise_node(config: AzureOpenAIConfig):
    """Categorise transactions.

    Bank rows are the source of truth — we run rules + LLM on them, deduplicated
    by the cleaner merchant name (enriched_counterparty when reconciliation
    has filled it). Wallet rows inherit their bank parent's category when
    linked; orphan wallet rows fall back to rule matching only (no LLM spend).
    """

    LLM_WORKERS = 8

    def categorise(state: PipelineState) -> PipelineState:
        repo = TransactionRepository(Path(state["db_path"]))
        all_txns = repo.get_transactions()
        if not all_txns:
            return {
                **state, "status": "categorised",
                "categorisation_summary": {"categorised": 0, "needs_review": 0},
            }

        bank_txns = [t for t in all_txns if t.source == TransactionSource.BANK]
        wallet_txns = [t for t in all_txns if t.source !=
                       TransactionSource.BANK]

        # --- Tier 1: rule-based on bank rows -------------------------------
        bank_uncategorised = [t for t in bank_txns if not t.category]
        rule_matched = 0
        needs_llm: list[Transaction] = []
        for t in bank_uncategorised:
            # Wallet tag (copied onto the bank row during reconciliation) is
            # ground truth; fall back to keyword rules on the enriched merchant.
            rule = categorise_by_tag(t.external_tag) or categorise_by_rules(
                _merchant_text(t))
            if rule:
                repo.set_category(
                    t.txn_id, rule.category, rule.subcategory,
                    rule.confidence, rule.confidence < REVIEW_THRESHOLD,
                )
                rule_matched += 1
            else:
                needs_llm.append(t)

        # --- Tier 2: LLM on remaining bank rows, deduped by merchant -------
        llm_calls = 0
        if needs_llm:
            llm = LLMProvider(config)
            unique_keys: dict[str, dict] = {}
            txn_to_key: dict[str, str] = {}
            for t in needs_llm:
                key = _merchant_text(t).upper().strip()[:60]
                txn_to_key[t.txn_id] = key
                if key not in unique_keys:
                    unique_keys[key] = {
                        "description": _merchant_text(t),
                        "amount": t.amount,
                        "direction": t.direction.value,
                    }

            results: dict[str, tuple[str, Optional[str], float]] = {}

            def _call(key: str, inp: dict):
                r = llm.categorise(inp["description"],
                                   inp["amount"], inp["direction"])
                return key, r

            with ThreadPoolExecutor(max_workers=LLM_WORKERS) as ex:
                futures = {ex.submit(_call, k, v): k for k,
                           v in unique_keys.items()}
                for fut in as_completed(futures):
                    key = futures[fut]
                    try:
                        key, r = fut.result()
                        results[key] = (
                            r.category, r.subcategory, r.confidence)
                        llm_calls += 1
                    except Exception as e:
                        logger.warning(
                            "LLM call failed for '%s': %s", key[:40], e)
                        results[key] = ("Other", None, 0.0)

            for t in needs_llm:
                cat, sub, conf = results.get(
                    txn_to_key[t.txn_id], ("Other", None, 0.0))
                repo.set_category(
                    t.txn_id, cat, sub, conf, conf < REVIEW_THRESHOLD,
                )

        # --- Wallet rows: inherit from linked bank parent ------------------
        bank_id_to_cat: dict[str, tuple[str, Optional[str], float]] = {}
        for t in repo.get_transactions(bank_only=True):
            if t.category:
                bank_id_to_cat[t.txn_id] = (
                    t.category, t.subcategory, t.confidence)

        wallet_inherited = 0
        wallet_rule_matched = 0
        for w in wallet_txns:
            if w.category:
                continue
            if w.linked_txn_id and w.linked_txn_id in bank_id_to_cat:
                cat, sub, conf = bank_id_to_cat[w.linked_txn_id]
                repo.set_category(w.txn_id, cat, sub, conf,
                                  conf < REVIEW_THRESHOLD)
                wallet_inherited += 1
            else:
                rule = categorise_by_tag(w.external_tag) or categorise_by_rules(
                    w.counterparty or w.raw_description)
                if rule:
                    repo.set_category(
                        w.txn_id, rule.category, rule.subcategory,
                        rule.confidence, rule.confidence < REVIEW_THRESHOLD,
                    )
                    wallet_rule_matched += 1

        needs_review = sum(
            1 for t in repo.get_transactions() if t.needs_review)
        logger.info(
            "Categorisation: bank rules=%d, bank llm=%d, wallet inherited=%d, wallet rules=%d.",
            rule_matched, llm_calls, wallet_inherited, wallet_rule_matched,
        )
        return {
            **state,
            "status": "categorised",
            "categorisation_summary": {
                "categorised": rule_matched + llm_calls + wallet_inherited + wallet_rule_matched,
                "bank_rule_matched": rule_matched,
                "bank_llm_calls": llm_calls,
                "wallet_inherited": wallet_inherited,
                "wallet_rule_matched": wallet_rule_matched,
                "needs_review": needs_review,
            },
        }

    return categorise


def _make_recurring_node():
    def detect_recurring(state: PipelineState) -> PipelineState:
        repo = TransactionRepository(Path(state["db_path"]))
        summary = run_recurring_detection(repo)
        return {**state, "status": "recurring_detected", "recurring_summary": summary}
    return detect_recurring


def _make_analytics_node():
    def compute_analytics(state: PipelineState) -> PipelineState:
        repo = TransactionRepository(Path(state["db_path"]))
        summary = run_analytics(repo)

        # Sanity check: the bank-only debit total must equal the sum of
        # monthly_maps.total_spend. If it doesn't, something double-counted.
        bank_debit_total = sum(
            t.amount for t in repo.get_transactions(bank_only=True, direction="debit")
        )
        maps_total = sum((m["total_spend"]
                         for m in summary.get("maps", [])), Decimal("0"))
        diff = (bank_debit_total - maps_total).copy_abs()
        summary["bank_debit_total"] = str(bank_debit_total)
        summary["maps_total"] = str(maps_total)
        summary["validate_diff"] = str(diff)
        logger.info(
            "analytics_validate: bank_debit_total=%s | monthly_maps_sum=%s | diff=%s",
            bank_debit_total, maps_total, diff,
        )

        errors = list(state.get("errors", []))
        if diff > Decimal("1"):
            errors.append(
                f"Monthly map total ({maps_total}) does not match bank debit total ({bank_debit_total})."
            )
        return {
            **state,
            "status": "analytics_computed",
            "analytics_summary": summary,
            "errors": errors,
        }
    return compute_analytics


def _make_anomaly_node(config: AzureOpenAIConfig):
    def detect_anomalies(state: PipelineState) -> PipelineState:
        repo = TransactionRepository(Path(state["db_path"]))
        summary = run_anomaly_detection(repo, config)
        return {**state, "status": "complete", "anomaly_summary": summary}
    return detect_anomalies


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_pipeline(config: AzureOpenAIConfig) -> StateGraph:
    """Build and compile the FinSight LangGraph pipeline."""
    builder = StateGraph(PipelineState)

    builder.add_node("ingest", _make_ingest_node(config))
    builder.add_node("reconcile", _make_reconcile_node())
    builder.add_node("categorise", _make_categorise_node(config))
    builder.add_node("detect_recurring", _make_recurring_node())
    builder.add_node("compute_analytics", _make_analytics_node())
    builder.add_node("detect_anomalies", _make_anomaly_node(config))

    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "reconcile")
    builder.add_edge("reconcile", "categorise")
    builder.add_edge("categorise", "detect_recurring")
    builder.add_edge("detect_recurring", "compute_analytics")
    builder.add_edge("compute_analytics", "detect_anomalies")
    builder.add_edge("detect_anomalies", END)

    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Public API used by Streamlit
# ---------------------------------------------------------------------------

def run_pipeline(
    config: AzureOpenAIConfig,
    db_path: Path,
    hdfc_path: Optional[Path] = None,
    gpay_path: Optional[Path] = None,
    paytm_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> PipelineState:
    """Run the full FinSight pipeline.

    progress_callback(label, fraction) is called as each node starts.
    Returns the final pipeline state.
    """
    graph = build_pipeline(config)
    thread = {"configurable": {"thread_id": "main"}}

    initial_state: PipelineState = {
        "hdfc_path": str(hdfc_path) if hdfc_path else None,
        "gpay_path": str(gpay_path) if gpay_path else None,
        "paytm_path": str(paytm_path) if paytm_path else None,
        "db_path": str(db_path),
        "status": "starting",
        "errors": [],
        "ingestion_summary": {},
        "reconciliation_summary": {},
        "categorisation_summary": {},
        "recurring_summary": {},
        "analytics_summary": {},
        "anomaly_summary": {},
    }

    steps = [
        ("ingest",            "Parsing statements…",                       0.10),
        ("reconcile",         "Linking bank ↔ wallet & enriching…",        0.25),
        ("categorise",        "Categorising bank rows (rules + LLM)…",     0.30),
        ("detect_recurring",  "Detecting recurring payments…",             0.75),
        ("compute_analytics", "Computing monthly maps & validating…",      0.85),
        ("detect_anomalies",  "Detecting anomalies…",                      0.95),
    ]
    if progress_callback:
        progress_callback(steps[0][1], steps[0][2])

    final_state = initial_state
    step_idx = 0
    for event in graph.stream(initial_state, thread):
        final_state = list(event.values())[0]
        step_idx += 1
        if progress_callback and step_idx < len(steps):
            label, frac = steps[step_idx][1], steps[step_idx][2]
            progress_callback(label, frac)

    if progress_callback:
        progress_callback("Complete ✅", 1.0)
    return final_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _merchant_text(txn: Transaction) -> str:
    """Description sent to rules & LLM. Prefers the enriched merchant name."""
    if txn.enriched_counterparty:
        return f"{txn.enriched_counterparty} | {txn.raw_description}"
    return txn.raw_description
