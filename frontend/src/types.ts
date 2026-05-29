// Mirrors backend/schemas.py — keep in sync when adding fields.

export interface Health {
  status: string;
  bank_transactions: number;
  enriched: number;
  enriched_pct: number;
  orphan_wallet: number;
  rag_indexed: number;
  rag_dense_enabled: boolean;
  data_min_date: string | null;
  data_max_date: string | null;
}

export interface Transaction {
  txn_id: string;
  source: string;
  source_ref: string;
  date: string;
  amount: string;
  direction: "debit" | "credit";
  raw_description: string;
  counterparty: string;
  enriched_counterparty: string | null;
  merchant: string;
  category: string;
  subcategory: string | null;
  is_recurring: boolean;
  recurring_type: string | null;
  linked_txn_id: string | null;
  confidence: number;
  needs_review: boolean;
  user_label: string | null;
}

export interface TransactionsResponse {
  transactions: Transaction[];
  count: number;
}

export interface CategorySummary {
  category: string;
  count: number;
  total: number;
}

export interface MerchantSummary {
  counterparty: string;
  count: number;
  total: number;
}

export interface MonthlyMap {
  month: string;
  income: string;
  total_spend: string;
  fixed_obligations: string;
  discretionary: string;
  net_savings: string;
  savings_rate: string;
}

export interface MonthlyCategoryCell {
  month: string;
  category: string;
  total: number;
}

export interface InsightsResponse {
  totals: { income: number; expense: number; net: number };
  categories: CategorySummary[];
  top_merchants: MerchantSummary[];
  monthly_maps: MonthlyMap[];
}

export interface RecurringSeries {
  series_id: string;
  counterparty: string;
  category: string;
  avg_amount: string;
  cadence: string;
  recurring_type: string | null;
  first_seen: string | null;
  last_seen: string | null;
  txn_count: number;
}

export interface ForecastProjection {
  month: string;
  income_mid: string;
  fixed: string;
  discretionary_low: string;
  discretionary_mid: string;
  discretionary_high: string;
  savings_low: string;
  savings_mid: string;
  savings_high: string;
}

export interface ForecastResponse {
  history: MonthlyMap[];
  projections: ForecastProjection[];
}

export interface GoalSuggestion {
  category?: string;
  action?: string;
  reduction_pct?: number;
  saving_amount?: number;
  rationale?: string;
}

export interface GoalAssessResponse {
  required_monthly: string;
  forecast_monthly: string;
  gap: string;
  verdict: "on_track" | "shortfall" | "surplus";
  suggestions: GoalSuggestion[];
  goal_id: string;
}

export interface WhatIfResponse {
  required_monthly: string;
  adjusted_savings: string;
  gap: string;
  verdict: "on_track" | "shortfall" | "surplus";
}

export interface PipelineResponse {
  status: string;
  errors: string[];
  ingestion: { total_parsed?: number; inserted?: number };
  reconciliation: {
    auto_linked?: number;
    enriched?: number;
    queued_for_review?: number;
    orphan_wallet?: number;
    backfilled?: number;
  };
  categorisation: {
    categorised?: number;
    bank_rule_matched?: number;
    bank_llm_calls?: number;
    wallet_inherited?: number;
    needs_review?: number;
  };
  recurring: { series_found?: number; transactions_marked?: number };
  analytics: { months_computed?: number; bank_debit_total?: string; maps_total?: string };
  anomaly: { flagged?: number };
}

export interface DateRange {
  start: string | null;
  end: string | null;
}
