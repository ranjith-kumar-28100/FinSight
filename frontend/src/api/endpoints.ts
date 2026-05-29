import { api, dateParams } from "./client";
import type {
  ForecastResponse,
  GoalAssessResponse,
  Health,
  InsightsResponse,
  MonthlyCategoryCell,
  MonthlyMap,
  PipelineResponse,
  RecurringSeries,
  Transaction,
  TransactionsResponse,
  WhatIfResponse,
} from "@/types";

// ---------- Health ----------
export const getHealth = async () => (await api.get<Health>("/health")).data;

// ---------- Upload ----------
export const runPipeline = async (files: {
  hdfc?: File;
  gpay?: File;
  paytm?: File;
}): Promise<PipelineResponse> => {
  const form = new FormData();
  if (files.hdfc) form.append("hdfc", files.hdfc);
  if (files.gpay) form.append("gpay", files.gpay);
  if (files.paytm) form.append("paytm", files.paytm);
  const { data } = await api.post<PipelineResponse>("/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
};

export const clearAllData = async () =>
  (await api.delete<{ deleted: number }>("/upload/data")).data;

// ---------- Transactions ----------
export const listTransactions = async (params: {
  start?: string | null;
  end?: string | null;
  category?: string;
  direction?: "debit" | "credit";
  source?: string;
  needs_review?: boolean;
  limit?: number;
}): Promise<TransactionsResponse> => {
  const { data } = await api.get<TransactionsResponse>("/transactions", {
    params: {
      ...dateParams(params.start ?? null, params.end ?? null),
      category: params.category,
      direction: params.direction,
      source: params.source,
      needs_review: params.needs_review,
      limit: params.limit ?? 500,
    },
  });
  return data;
};

export const getOrphans = async () =>
  (await api.get<TransactionsResponse>("/transactions/orphans")).data;

export const getWalletDetail = async (bankTxnId: string) =>
  (await api.get<TransactionsResponse>(`/transactions/${bankTxnId}/wallet-detail`))
    .data;

export const updateLabel = async (txnId: string, label: string) =>
  (await api.patch<{ ok: boolean }>(`/transactions/${txnId}/label`, { label }))
    .data;

// ---------- Analytics ----------
export const getInsights = async (
  start: string | null,
  end: string | null
): Promise<InsightsResponse> => {
  const { data } = await api.get<InsightsResponse>("/analytics/insights", {
    params: dateParams(start, end),
  });
  return data;
};

export const getMonthlyMaps = async (
  start: string | null,
  end: string | null
): Promise<MonthlyMap[]> => {
  const { data } = await api.get<MonthlyMap[]>("/analytics/monthly-maps", {
    params: dateParams(start, end),
  });
  return data;
};

export const getCategoryHeatmap = async (
  start: string | null,
  end: string | null
): Promise<MonthlyCategoryCell[]> => {
  const { data } = await api.get<MonthlyCategoryCell[]>(
    "/analytics/category-heatmap",
    { params: dateParams(start, end) }
  );
  return data;
};

// ---------- Recurring ----------
export const getRecurring = async (
  start: string | null,
  end: string | null
): Promise<RecurringSeries[]> => {
  const { data } = await api.get<RecurringSeries[]>("/recurring", {
    params: dateParams(start, end),
  });
  return data;
};

// ---------- Forecast ----------
export const getForecast = async (
  horizon: number,
  start: string | null,
  end: string | null
): Promise<ForecastResponse> => {
  const { data } = await api.get<ForecastResponse>("/forecast", {
    params: { horizon, ...dateParams(start, end) },
  });
  return data;
};

// ---------- Goals ----------
export const assessGoal = async (body: {
  target_amount: number;
  horizon_months: number;
  description?: string;
  start: string | null;
  end: string | null;
}) => (await api.post<GoalAssessResponse>("/goals/assess", body)).data;

export const whatIf = async (body: {
  target_amount: number;
  horizon_months: number;
  adjustments: Record<string, number>;
  start: string | null;
  end: string | null;
}) => (await api.post<WhatIfResponse>("/goals/what-if", body)).data;

// ---------- Anomalies ----------
export const getAnomalies = async (
  start: string | null,
  end: string | null
) =>
  (
    await api.get<TransactionsResponse>("/anomalies", {
      params: dateParams(start, end),
    })
  ).data;

// ---------- Chat ----------
export const chat = async (
  message: string,
  start: string | null,
  end: string | null
) => {
  const { data } = await api.post<{ answer: string }>("/chat", {
    message,
    start,
    end,
  });
  return data;
};

export const resetChat = async () =>
  (await api.post<{ ok: boolean }>("/chat/reset", {})).data;
