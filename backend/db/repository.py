"""Database CRUD operations.

All queries use parameterized statements — no string concatenation.
"""

import json
import logging
import sqlite3
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from backend.models.transaction import (
    Provenance,
    RecurringType,
    Transaction,
    TransactionDirection,
    TransactionSource,
)

logger = logging.getLogger(__name__)


def _safe_col(row: "sqlite3.Row", name: str):
    """Read an optional column that may be absent on older DB rows."""
    try:
        return row[name] or None
    except (IndexError, KeyError):
        return None


class TransactionRepository:
    """CRUD operations for the transactions table.

    Uses parameterized queries exclusively to prevent SQL injection.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection for each operation."""
        return sqlite3.connect(self._db_path)

    def insert_transactions(self, transactions: list[Transaction]) -> int:
        """Bulk insert transactions. Returns count of inserted rows.

        Uses INSERT OR IGNORE to handle duplicate txn_ids idempotently.
        """
        sql = """
            INSERT OR IGNORE INTO transactions (
                txn_id, source, source_ref, date, amount, direction,
                raw_description, counterparty, enriched_counterparty,
                upi_id, counterparty_app, txn_time, external_tag,
                category, subcategory,
                is_recurring, recurring_type, linked_txn_id, confidence,
                needs_review, user_label, provenance_file, provenance_row,
                provenance_sheet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = []
        for txn in transactions:
            rows.append((
                txn.txn_id,
                txn.source.value,
                txn.source_ref,
                txn.date.isoformat(),
                str(txn.amount),
                txn.direction.value,
                txn.raw_description,
                txn.counterparty,
                txn.enriched_counterparty,
                txn.upi_id,
                txn.counterparty_app,
                txn.txn_time,
                txn.external_tag,
                txn.category,
                txn.subcategory,
                int(txn.is_recurring),
                txn.recurring_type.value if txn.recurring_type else None,
                txn.linked_txn_id,
                txn.confidence,
                int(txn.needs_review),
                txn.user_label,
                txn.provenance.source_file if txn.provenance else None,
                txn.provenance.row_index if txn.provenance else None,
                txn.provenance.sheet_name if txn.provenance else None,
            ))

        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()
            inserted = cursor.rowcount
            logger.info("Inserted %d transactions.", inserted)
            return inserted
        finally:
            conn.close()

    def get_transactions(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        category: Optional[str] = None,
        direction: Optional[str] = None,
        source: Optional[str] = None,
        needs_review: Optional[bool] = None,
        bank_only: bool = False,
    ) -> list[Transaction]:
        """Query transactions with optional filters.

        All filters use parameterized queries.

        bank_only=True restricts to bank rows — used by analytics, recurring,
        and any aggregation where the bank statement is the source of truth.
        """
        conditions = []
        params: list = []

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())
        if category:
            conditions.append("category = ?")
            params.append(category)
        if direction:
            conditions.append("direction = ?")
            params.append(direction)
        if bank_only:
            conditions.append("source = ?")
            params.append("bank")
        elif source:
            conditions.append("source = ?")
            params.append(source)
        if needs_review is not None:
            conditions.append("needs_review = ?")
            params.append(int(needs_review))

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"SELECT * FROM transactions {where_clause} ORDER BY date DESC"

        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_transaction(row) for row in rows]
        finally:
            conn.close()

    def get_date_range(self) -> tuple[Optional[date], Optional[date]]:
        """Get the min and max transaction dates in the database."""
        sql = "SELECT MIN(date), MAX(date) FROM transactions"
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            if row and row[0] and row[1]:
                return (
                    date.fromisoformat(row[0]),
                    date.fromisoformat(row[1]),
                )
            return None, None
        finally:
            conn.close()

    def get_categories_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """Aggregate spend by category within optional date range.

        Bank source only — wallet rows are enrichment, never counted.
        """
        conditions = ["direction = ?", "source = ?"]
        params: list = ["debit", "bank"]

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT category, COUNT(*) as txn_count, SUM(CAST(amount AS REAL)) as total
            FROM transactions
            {where_clause}
            GROUP BY category
            ORDER BY total DESC
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [
                {"category": row[0] or "Uncategorised",
                    "count": row[1], "total": round(row[2], 2)}
                for row in rows
            ]
        finally:
            conn.close()

    def get_income_expense_totals(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        """Get total income and expense within optional date range.

        Bank source only — wallet rows are enrichment, never counted.
        """
        conditions: list[str] = ["source = ?"]
        params: list = ["bank"]

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT direction, SUM(CAST(amount AS REAL)) as total
            FROM transactions
            {where_clause}
            GROUP BY direction
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            result = {"income": 0.0, "expense": 0.0}
            for row in rows:
                if row[0] == "credit":
                    result["income"] = round(row[1], 2)
                elif row[0] == "debit":
                    result["expense"] = round(row[1], 2)
            return result
        finally:
            conn.close()

    def get_top_counterparties(
        self,
        limit: int = 10,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """Get top counterparties by spend.

        Bank source only. Uses enriched_counterparty when available, falling
        back to the raw bank counterparty.
        """
        conditions = ["direction = ?", "source = ?", "counterparty != ''"]
        params: list = ["debit", "bank"]

        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT COALESCE(NULLIF(enriched_counterparty, ''), counterparty) AS merchant,
                   COUNT(*) as txn_count,
                   SUM(CAST(amount AS REAL)) as total
            FROM transactions
            {where_clause}
            GROUP BY merchant
            ORDER BY total DESC
            LIMIT ?
        """
        params.append(limit)

        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [
                {"counterparty": row[0], "count": row[1],
                    "total": round(row[2], 2)}
                for row in rows
            ]
        finally:
            conn.close()

    def update_user_label(self, txn_id: str, label: str) -> bool:
        """Update user-provided label for a transaction."""
        sql = """
            UPDATE transactions
            SET user_label = ?, needs_review = 0
            WHERE txn_id = ?
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (label, txn_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_source_counts(self) -> dict[str, int]:
        """Get transaction count per source."""
        sql = "SELECT source, COUNT(*) FROM transactions GROUP BY source"
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            return {row[0]: row[1] for row in cursor.fetchall()}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Reconciliation + enrichment
    # ------------------------------------------------------------------

    def link_transactions(self, primary_id: str, wallet_id: str, confidence: float) -> None:
        """Link a wallet transaction to its bank counterpart (deduplication)."""
        sql = "UPDATE transactions SET linked_txn_id = ?, confidence = ? WHERE txn_id = ?"
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (primary_id, confidence, wallet_id))
            conn.commit()
        finally:
            conn.close()

    def update_enriched_counterparty(self, bank_txn_id: str, name: str) -> None:
        """Write the cleaned merchant name from the wallet side onto a bank row."""
        if not name:
            return
        sql = "UPDATE transactions SET enriched_counterparty = ? WHERE txn_id = ?"
        conn = self._connect()
        try:
            conn.execute(sql, (name, bank_txn_id))
            conn.commit()
        finally:
            conn.close()

    def enrich_bank_row(
        self,
        bank_txn_id: str,
        enriched_counterparty: Optional[str] = None,
        upi_id: Optional[str] = None,
        counterparty_app: Optional[str] = None,
        external_tag: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
    ) -> None:
        """Push wallet-derived context onto a linked bank backbone row.

        Only the supplied columns are written. ``upi_id`` / ``counterparty_app``
        are filled only when the bank row is missing them (COALESCE); the
        wallet-owned fields (enriched name, tag, adopted category) overwrite.
        """
        sets: list[str] = []
        params: list = []
        if enriched_counterparty:
            sets.append("enriched_counterparty = ?")
            params.append(enriched_counterparty)
        if upi_id:
            sets.append("upi_id = COALESCE(NULLIF(upi_id, ''), ?)")
            params.append(upi_id)
        if counterparty_app:
            sets.append("counterparty_app = COALESCE(NULLIF(counterparty_app, ''), ?)")
            params.append(counterparty_app)
        if external_tag:
            sets.append("external_tag = ?")
            params.append(external_tag)
        if category:
            sets.append("category = ?")
            params.append(category)
            sets.append("subcategory = ?")
            params.append(subcategory)
        if not sets:
            return
        params.append(bank_txn_id)
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE transactions SET {', '.join(sets)} WHERE txn_id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

    def get_unlinked_by_source(self, source: str) -> list[Transaction]:
        """Return transactions from a specific source that have no reconciliation link."""
        sql = """
            SELECT * FROM transactions
            WHERE source = ? AND (linked_txn_id IS NULL OR linked_txn_id = '')
            ORDER BY date
        """
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, (source,))
            return [self._row_to_transaction(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_wallet_detail_for_bank(self, bank_txn_id: str) -> list[Transaction]:
        """Return wallet rows that reconciliation linked to this bank txn."""
        sql = """
            SELECT * FROM transactions
            WHERE source IN ('gpay', 'paytm') AND linked_txn_id = ?
            ORDER BY date
        """
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, (bank_txn_id,))
            return [self._row_to_transaction(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_orphan_wallet_transactions(self) -> list[Transaction]:
        """Return wallet rows with no bank counterpart — kept for traceability."""
        sql = """
            SELECT * FROM transactions
            WHERE source IN ('gpay', 'paytm')
              AND (linked_txn_id IS NULL OR linked_txn_id = '')
            ORDER BY date DESC
        """
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            return [self._row_to_transaction(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_enrichment_stats(self) -> dict:
        """Return a small summary used by the sidebar."""
        sql = """
            SELECT
              SUM(CASE WHEN source = 'bank' THEN 1 ELSE 0 END) AS bank_total,
              SUM(CASE WHEN source = 'bank'
                       AND enriched_counterparty IS NOT NULL
                       AND enriched_counterparty != '' THEN 1 ELSE 0 END) AS enriched,
              SUM(CASE WHEN source IN ('gpay', 'paytm')
                       AND (linked_txn_id IS NULL OR linked_txn_id = '')
                       THEN 1 ELSE 0 END) AS orphan_wallet
            FROM transactions
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone() or (0, 0, 0)
            bank_total = row[0] or 0
            enriched = row[1] or 0
            orphan = row[2] or 0
            return {
                "bank_total": bank_total,
                "enriched": enriched,
                "enriched_pct": (enriched / bank_total) if bank_total else 0.0,
                "orphan_wallet": orphan,
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Categorisation
    # ------------------------------------------------------------------

    def set_category(
        self,
        txn_id: str,
        category: str,
        subcategory: Optional[str],
        confidence: float,
        needs_review: bool,
    ) -> None:
        """Update a transaction's category fields."""
        sql = """
            UPDATE transactions
            SET category = ?, subcategory = ?, confidence = ?, needs_review = ?
            WHERE txn_id = ?
        """
        conn = self._connect()
        try:
            conn.execute(
                sql,
                (category, subcategory, confidence, int(needs_review), txn_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Recurring series
    # ------------------------------------------------------------------

    def insert_recurring_series(self, series: list[dict]) -> int:
        """Bulk insert recurring series rows. Returns count inserted."""
        sql = """
            INSERT OR REPLACE INTO recurring_series
            (series_id, counterparty, category, avg_amount, cadence,
             recurring_type, first_seen, last_seen, txn_count, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        rows = [
            (
                s.get("series_id", str(uuid.uuid4())),
                s["counterparty"],
                s.get("category", ""),
                str(s["avg_amount"]),
                s["cadence"],
                s.get("recurring_type"),
                s.get("first_seen"),
                s.get("last_seen"),
                s.get("txn_count", 0),
            )
            for s in series
        ]
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, rows)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_recurring_series(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """Return active recurring series, optionally restricted to those whose
        activity overlaps the given date range.

        A series overlaps the range when ``first_seen <= end_date`` AND
        ``last_seen >= start_date``."""
        conditions = ["is_active = 1"]
        params: list = []
        if end_date:
            conditions.append("(first_seen IS NULL OR first_seen <= ?)")
            params.append(end_date.isoformat())
        if start_date:
            conditions.append("(last_seen IS NULL OR last_seen >= ?)")
            params.append(start_date.isoformat())
        sql = (
            "SELECT * FROM recurring_series "
            f"WHERE {' AND '.join(conditions)} ORDER BY avg_amount DESC"
        )
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def mark_recurring(self, txn_ids: list[str], recurring_type: Optional[str]) -> int:
        """Set is_recurring=1 on the given transaction IDs."""
        if not txn_ids:
            return 0
        placeholders = ",".join("?" * len(txn_ids))
        sql = f"""
            UPDATE transactions
            SET is_recurring = 1, recurring_type = ?
            WHERE txn_id IN ({placeholders})
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, [recurring_type] + txn_ids)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Monthly maps
    # ------------------------------------------------------------------

    def upsert_monthly_map(self, month: str, income: Decimal, total_spend: Decimal,
                           fixed: Decimal, discretionary: Decimal,
                           net_savings: Decimal, savings_rate: Decimal) -> None:
        """Insert or replace a monthly money-map row."""
        sql = """
            INSERT OR REPLACE INTO monthly_maps
            (month, income, total_spend, fixed_obligations, discretionary,
             net_savings, savings_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (
                month, str(income), str(total_spend), str(fixed),
                str(discretionary), str(net_savings), str(savings_rate),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_monthly_maps(self) -> list[dict]:
        """Return all monthly maps ordered chronologically."""
        sql = "SELECT * FROM monthly_maps ORDER BY month"
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
            return [
                {
                    "month": r["month"],
                    "income": Decimal(r["income"]),
                    "total_spend": Decimal(r["total_spend"]),
                    "fixed_obligations": Decimal(r["fixed_obligations"]),
                    "discretionary": Decimal(r["discretionary"]),
                    "net_savings": Decimal(r["net_savings"]),
                    "savings_rate": Decimal(r["savings_rate"]),
                }
                for r in rows
            ]
        finally:
            conn.close()

    def get_monthly_category_breakdown(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[dict]:
        """Return spend per category per month for trend analysis.

        Bank source only.
        """
        conditions = ["direction = 'debit'",
                      "source = 'bank'", "category != ''"]
        params: list = []
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())
        sql = f"""
            SELECT strftime('%Y-%m', date) as month, category,
                   SUM(CAST(amount AS REAL)) as total
            FROM transactions
            WHERE {" AND ".join(conditions)}
            GROUP BY month, category
            ORDER BY month, total DESC
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [
                {"month": r[0], "category": r[1], "total": round(r[2], 2)}
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def save_goal(self, description: str, target_amount: Decimal,
                  horizon_months: int, verdict: str,
                  gap_per_month: Decimal, suggestions: list[dict]) -> str:
        """Persist a goal analysis result. Returns the goal_id."""
        goal_id = str(uuid.uuid4())
        sql = """
            INSERT INTO goals
            (goal_id, description, target_amount, horizon_months, verdict,
             gap_per_month, suggestions)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (
                goal_id, description, str(target_amount), horizon_months,
                verdict, str(gap_per_month), json.dumps(suggestions),
            ))
            conn.commit()
            return goal_id
        finally:
            conn.close()

    def get_latest_goal(self) -> Optional[dict]:
        """Return the most recently saved goal, or None."""
        sql = "SELECT * FROM goals ORDER BY created_at DESC LIMIT 1"
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "goal_id": row["goal_id"],
                "description": row["description"],
                "target_amount": Decimal(row["target_amount"]),
                "horizon_months": row["horizon_months"],
                "verdict": row["verdict"],
                "gap_per_month": Decimal(row["gap_per_month"]),
                "suggestions": json.loads(row["suggestions"]),
                "created_at": row["created_at"],
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Anomaly helpers
    # ------------------------------------------------------------------

    def get_transactions_for_anomaly(self) -> list[dict]:
        """Return minimal transaction data for anomaly detection.

        Bank source only.
        """
        sql = """
            SELECT txn_id, date, amount, category, direction,
                   COALESCE(NULLIF(enriched_counterparty, ''), counterparty) AS merchant
            FROM transactions
            WHERE direction = 'debit' AND source = 'bank'
            ORDER BY date
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            return [
                {
                    "txn_id": r[0],
                    "date": r[1],
                    "amount": Decimal(r[2]),
                    "category": r[3] or "Other",
                    "direction": r[4],
                    "counterparty": r[5] or "",
                }
                for r in cursor.fetchall()
            ]
        finally:
            conn.close()

    def flag_anomalies(self, txn_ids: list[str]) -> int:
        """Set needs_review = 1 on the given transaction IDs."""
        if not txn_ids:
            return 0
        placeholders = ",".join("?" * len(txn_ids))
        sql = f"UPDATE transactions SET needs_review = 1 WHERE txn_id IN ({placeholders})"
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, txn_ids)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Chat helpers
    # ------------------------------------------------------------------

    def get_category_total(self, category: str,
                           start_date: Optional[date] = None,
                           end_date: Optional[date] = None) -> dict:
        """Return total spend and count for one category in a date range.

        Bank source only.
        """
        conditions = ["direction = 'debit'", "source = 'bank'", "category = ?"]
        params: list = [category]
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date.isoformat())
        sql = f"""
            SELECT COUNT(*), SUM(CAST(amount AS REAL))
            FROM transactions WHERE {" AND ".join(conditions)}
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return {"count": row[0] or 0, "total": round(row[1] or 0, 2)}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clear_all(self) -> int:
        """Delete all transactions. Returns count of deleted rows."""
        sql = "DELETE FROM transactions"
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            conn.commit()
            deleted = cursor.rowcount
            # Also clear derived tables
            for tbl in ("recurring_series", "monthly_maps", "goals"):
                conn.execute(f"DELETE FROM {tbl}")
            conn.commit()
            logger.info("Cleared %d transactions.", deleted)
            return deleted
        finally:
            conn.close()

    @staticmethod
    def _row_to_transaction(row: sqlite3.Row) -> Transaction:
        """Convert a database row to a Transaction model."""
        provenance = None
        if row["provenance_file"]:
            provenance = Provenance(
                source_file=row["provenance_file"],
                row_index=row["provenance_row"],
                sheet_name=row["provenance_sheet"],
            )

        enriched = None
        try:
            enriched = row["enriched_counterparty"] or None
        except (IndexError, KeyError):
            enriched = None

        return Transaction(
            txn_id=row["txn_id"],
            source=TransactionSource(row["source"]),
            source_ref=row["source_ref"] or "",
            date=date.fromisoformat(row["date"]),
            amount=Decimal(row["amount"]),
            direction=TransactionDirection(row["direction"]),
            raw_description=row["raw_description"],
            counterparty=row["counterparty"] or "",
            enriched_counterparty=enriched,
            upi_id=_safe_col(row, "upi_id"),
            counterparty_app=_safe_col(row, "counterparty_app"),
            txn_time=_safe_col(row, "txn_time"),
            external_tag=_safe_col(row, "external_tag"),
            category=row["category"] or "",
            subcategory=row["subcategory"],
            is_recurring=bool(row["is_recurring"]),
            recurring_type=row["recurring_type"],
            linked_txn_id=row["linked_txn_id"],
            confidence=row["confidence"] or 0.0,
            needs_review=bool(row["needs_review"]),
            user_label=row["user_label"],
            provenance=provenance,
        )
