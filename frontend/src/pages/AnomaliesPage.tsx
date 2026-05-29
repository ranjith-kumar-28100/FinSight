import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check } from "lucide-react";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { getAnomalies, updateLabel } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { inr, shortDate } from "@/lib/format";

export function AnomaliesPage() {
  const { start, end } = useDateRange();
  const queryClient = useQueryClient();

  const q = useQuery({
    queryKey: ["anomalies", start, end],
    queryFn: () => getAnomalies(start, end),
    enabled: start !== null && end !== null,
  });

  const [labels, setLabels] = useState<Record<string, string>>({});
  const updateM = useMutation({
    mutationFn: ({ id, label }: { id: string; label: string }) => updateLabel(id, label),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["anomalies"] }),
  });

  if (q.isLoading) return <Spinner />;
  if (!q.data || q.data.count === 0) {
    return (
      <Card>
        <EmptyState
          title="Nothing to review"
          description="No flagged transactions in this date range."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50 flex items-center gap-2">
          <AlertTriangle className="h-6 w-6 text-gold-400" />
          Anomalies & Review
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          {q.data.count} transaction{q.data.count === 1 ? "" : "s"} flagged in {start} → {end}.
        </p>
      </div>

      <div className="space-y-3">
        {q.data.transactions.map((t) => (
          <Card key={t.txn_id}>
            <div className="flex flex-wrap items-start gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-lg font-semibold text-slate-100">
                    {t.merchant || t.raw_description.slice(0, 32)}
                  </span>
                  <span className="text-xs text-slate-400 tabular">
                    {shortDate(t.date)} · {t.source.toUpperCase()}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-500 break-all">{t.raw_description}</p>
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="chip">
                    {t.category || "Uncategorised"} · {(t.confidence * 100).toFixed(0)}%
                  </span>
                  {t.user_label && <span className="chip-gold">Your note: {t.user_label}</span>}
                </div>
              </div>
              <div className="text-right">
                <div
                  className={
                    t.direction === "credit"
                      ? "text-gain-400 text-xl font-semibold tabular"
                      : "text-loss-400 text-xl font-semibold tabular"
                  }
                >
                  {t.direction === "credit" ? "+" : "−"}
                  {inr(t.amount, true)}
                </div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <input
                className="input flex-1"
                placeholder="Add a note to confirm this transaction…"
                value={labels[t.txn_id] ?? ""}
                onChange={(e) => setLabels({ ...labels, [t.txn_id]: e.target.value })}
              />
              <button
                className="btn-primary"
                disabled={updateM.isPending || !labels[t.txn_id]}
                onClick={() =>
                  updateM.mutate({ id: t.txn_id, label: labels[t.txn_id] || "Reviewed" })
                }
              >
                <Check className="h-4 w-4" /> Confirm
              </button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
