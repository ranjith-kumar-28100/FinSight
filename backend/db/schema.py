"""SQLite schema creation.

Creates the transactions table using the canonical schema.
All DDL is idempotent (CREATE IF NOT EXISTS).
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# DDL for the canonical transactions table
_CREATE_TRANSACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS transactions (
    txn_id          TEXT PRIMARY KEY,
    source          TEXT NOT NULL CHECK(source IN ('bank', 'gpay', 'paytm')),
    source_ref      TEXT DEFAULT '',
    date            TEXT NOT NULL,
    amount          TEXT NOT NULL,
    direction       TEXT NOT NULL CHECK(direction IN ('debit', 'credit')),
    raw_description TEXT NOT NULL,
    counterparty    TEXT DEFAULT '',
    enriched_counterparty TEXT,
    upi_id          TEXT,
    counterparty_app TEXT,
    txn_time        TEXT,
    external_tag    TEXT,
    category        TEXT DEFAULT '',
    subcategory     TEXT,
    is_recurring    INTEGER DEFAULT 0,
    recurring_type  TEXT,
    linked_txn_id   TEXT,
    confidence      REAL DEFAULT 0.0,
    needs_review    INTEGER DEFAULT 0,
    user_label      TEXT,
    provenance_file TEXT,
    provenance_row  INTEGER,
    provenance_sheet TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_RECURRING_SERIES_TABLE = """
CREATE TABLE IF NOT EXISTS recurring_series (
    series_id      TEXT PRIMARY KEY,
    counterparty   TEXT NOT NULL,
    category       TEXT DEFAULT '',
    avg_amount     TEXT NOT NULL,
    cadence        TEXT NOT NULL,
    recurring_type TEXT,
    first_seen     TEXT,
    last_seen      TEXT,
    txn_count      INTEGER DEFAULT 0,
    is_active      INTEGER DEFAULT 1
);
"""

_CREATE_MONTHLY_MAPS_TABLE = """
CREATE TABLE IF NOT EXISTS monthly_maps (
    month              TEXT PRIMARY KEY,
    income             TEXT NOT NULL,
    total_spend        TEXT NOT NULL,
    fixed_obligations  TEXT NOT NULL,
    discretionary      TEXT NOT NULL,
    net_savings        TEXT NOT NULL,
    savings_rate       TEXT NOT NULL
);
"""

_CREATE_GOALS_TABLE = """
CREATE TABLE IF NOT EXISTS goals (
    goal_id        TEXT PRIMARY KEY,
    description    TEXT DEFAULT '',
    target_amount  TEXT NOT NULL,
    horizon_months INTEGER NOT NULL,
    verdict        TEXT DEFAULT '',
    gap_per_month  TEXT DEFAULT '0',
    suggestions    TEXT DEFAULT '[]',
    created_at     TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_source ON transactions(source);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_ref ON transactions(source_ref);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_needs_review ON transactions(needs_review);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_linked ON transactions(linked_txn_id);",
    "CREATE INDEX IF NOT EXISTS idx_transactions_recurring ON transactions(is_recurring);",
]


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Idempotently add columns that aren't part of older databases."""
    existing = {row[1]
                for row in conn.execute("PRAGMA table_info(transactions)")}
    # Each new column added in its own ALTER so older DBs migrate cleanly.
    for col in (
        "enriched_counterparty",
        "upi_id",
        "counterparty_app",
        "txn_time",
        "external_tag",
    ):
        if col not in existing:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} TEXT")
            logger.info("Migrated transactions table: added %s column.", col)


def init_db(db_path: Path) -> None:
    """Initialise the SQLite database with the canonical schema.

    Safe to call multiple times — uses IF NOT EXISTS.
    Binds to the specific file path, never to a network address.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Initialising database at %s", db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        cursor.execute(_CREATE_TRANSACTIONS_TABLE)
        cursor.execute(_CREATE_RECURRING_SERIES_TABLE)
        cursor.execute(_CREATE_MONTHLY_MAPS_TABLE)
        cursor.execute(_CREATE_GOALS_TABLE)
        for idx_sql in _CREATE_INDEXES:
            cursor.execute(idx_sql)
        _ensure_columns(conn)
        conn.commit()
        logger.info("Database schema initialised successfully.")
    finally:
        conn.close()
