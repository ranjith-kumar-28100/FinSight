"""Pydantic request/response schemas for the FinSight API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------

class DateRange(BaseModel):
    start: Optional[date] = None
    end: Optional[date] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    bank_transactions: int = 0
    enriched: int = 0
    enriched_pct: float = 0.0
    orphan_wallet: int = 0
    rag_indexed: int = 0
    rag_dense_enabled: bool = False
    data_min_date: Optional[date] = None
    data_max_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class TransactionOut(BaseModel):
    txn_id: str
    source: str
    source_ref: str
    date: date
    amount: Decimal
    direction: str
    raw_description: str
    counterparty: str
    enriched_counterparty: Optional[str] = None
    merchant: str  # enriched_counterparty || counterparty
    category: str
    subcategory: Optional[str] = None
    is_recurring: bool
    recurring_type: Optional[str] = None
    linked_txn_id: Optional[str] = None
    confidence: float
    needs_review: bool
    user_label: Optional[str] = None


class TransactionsResponse(BaseModel):
    transactions: list[TransactionOut]
    count: int


class UpdateLabelRequest(BaseModel):
    label: str


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class IncomeExpense(BaseModel):
    income: float
    expense: float
    net: float


class CategorySummary(BaseModel):
    category: str
    count: int
    total: float


class MerchantSummary(BaseModel):
    counterparty: str
    count: int
    total: float


class MonthlyMap(BaseModel):
    month: str
    income: Decimal
    total_spend: Decimal
    fixed_obligations: Decimal
    discretionary: Decimal
    net_savings: Decimal
    savings_rate: Decimal


class MonthlyCategoryCell(BaseModel):
    month: str
    category: str
    total: float


class InsightsResponse(BaseModel):
    totals: IncomeExpense
    categories: list[CategorySummary]
    top_merchants: list[MerchantSummary]
    monthly_maps: list[MonthlyMap]


# ---------------------------------------------------------------------------
# Recurring
# ---------------------------------------------------------------------------

class RecurringSeries(BaseModel):
    series_id: str
    counterparty: str
    category: str
    avg_amount: Decimal
    cadence: str
    recurring_type: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    txn_count: int


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

class ForecastProjection(BaseModel):
    month: str
    income_mid: Decimal
    fixed: Decimal
    discretionary_low: Decimal
    discretionary_mid: Decimal
    discretionary_high: Decimal
    savings_low: Decimal
    savings_mid: Decimal
    savings_high: Decimal


class ForecastResponse(BaseModel):
    history: list[MonthlyMap]
    projections: list[ForecastProjection]


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

class GoalAssessRequest(BaseModel):
    target_amount: Decimal = Field(gt=0)
    horizon_months: int = Field(gt=0, le=120)
    description: str = ""
    start: Optional[date] = None
    end: Optional[date] = None


class WhatIfRequest(BaseModel):
    target_amount: Decimal = Field(gt=0)
    horizon_months: int = Field(gt=0, le=120)
    adjustments: dict[str, Decimal] = Field(default_factory=dict)
    start: Optional[date] = None
    end: Optional[date] = None


class GoalSuggestion(BaseModel):
    category: str = ""
    action: str = ""
    reduction_pct: float = 0
    saving_amount: float = 0
    rationale: str = ""


class GoalAssessResponse(BaseModel):
    required_monthly: Decimal
    forecast_monthly: Decimal
    gap: Decimal
    verdict: str
    suggestions: list[dict[str, Any]]
    goal_id: str


class WhatIfResponse(BaseModel):
    required_monthly: Decimal
    adjusted_savings: Decimal
    gap: Decimal
    verdict: str


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    start: Optional[date] = None
    end: Optional[date] = None


class ChatResponse(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# Upload + pipeline
# ---------------------------------------------------------------------------

class IngestionSummary(BaseModel):
    total_parsed: int = 0
    inserted: int = 0


class ReconciliationSummary(BaseModel):
    auto_linked: int = 0
    enriched: int = 0
    queued_for_review: int = 0
    orphan_wallet: int = 0
    backfilled: int = 0


class CategorisationSummary(BaseModel):
    categorised: int = 0
    bank_rule_matched: int = 0
    bank_llm_calls: int = 0
    wallet_inherited: int = 0
    wallet_rule_matched: int = 0
    needs_review: int = 0


class PipelineResponse(BaseModel):
    status: str
    errors: list[str] = []
    ingestion: dict[str, Any] = {}
    reconciliation: dict[str, Any] = {}
    categorisation: dict[str, Any] = {}
    recurring: dict[str, Any] = {}
    analytics: dict[str, Any] = {}
    anomaly: dict[str, Any] = {}
