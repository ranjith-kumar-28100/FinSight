"""Canonical transaction schema.

All data sources (HDFC, Paytm, GPay) normalise into this single schema
so downstream agents are source-agnostic.

Uses Decimal for all monetary values — never float.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class TransactionSource(str, enum.Enum):
    """Source of the transaction data."""

    BANK = "bank"
    GPAY = "gpay"
    PAYTM = "paytm"


class TransactionDirection(str, enum.Enum):
    """Whether money went out (debit) or came in (credit)."""

    DEBIT = "debit"
    CREDIT = "credit"


class RecurringType(str, enum.Enum):
    """Type of recurring transaction (Phase 2+)."""

    EMI = "emi"
    SIP = "sip"
    SUBSCRIPTION = "subscription"
    INSURANCE = "insurance"
    RENT = "rent"
    UTILITY = "utility"


class Provenance(BaseModel):
    """Tracks which source file and row a transaction came from."""

    source_file: str
    row_index: Optional[int] = None
    sheet_name: Optional[str] = None


class Transaction(BaseModel):
    """Canonical transaction record.

    Every transaction from every source maps to this schema.
    Downstream agents (categorisation, analytics, forecast) only work
    with this model.
    """

    txn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: TransactionSource
    source_ref: str = ""  # normalised UPI RRN (leading zeros stripped) — cross-source join key
    date: date
    amount: Decimal = Field(ge=0)
    direction: TransactionDirection
    raw_description: str
    counterparty: str = ""
    enriched_counterparty: Optional[str] = None
    # -- Enrichment fields (populated from wallet exports / narration) --------
    upi_id: Optional[str] = None        # counterparty VPA, e.g. "zepto.payu@axisbank"
    counterparty_app: Optional[str] = None  # app the counterparty collects on: PhonePe/Google Pay/Paytm
    txn_time: Optional[str] = None      # HH:MM:SS within the day (wallets carry this; bank does not)
    external_tag: Optional[str] = None  # user's own category tag from the wallet (Paytm "Tags")
    category: str = ""
    subcategory: Optional[str] = None
    is_recurring: bool = False
    recurring_type: Optional[RecurringType] = None
    linked_txn_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    user_label: Optional[str] = None
    provenance: Optional[Provenance] = None

    class Config:
        """Pydantic model configuration."""

        # Allow Decimal fields to be serialized as strings for JSON
        json_encoders = {Decimal: str}
