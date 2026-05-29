import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { getInsights } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { inr } from "@/lib/format";

export function InsightsPage() {
  const { start, end } = useDateRange();
  const q = useQuery({
    queryKey: ["insights-table", start, end],
    queryFn: () => getInsights(start, end),
    enabled: start !== null && end !== null,
  });

  if (q.isLoading) return <Spinner />;

  const categories = q.data?.categories ?? [];
  const top_merchants = q.data?.top_merchants ?? [];
  const hasData = categories.length > 0 || top_merchants.length > 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50">Insights</h1>
        <p className="mt-1 text-sm text-slate-400">
          Full category and merchant breakdown — {start} → {end}
        </p>
      </div>

      <Card title="Category breakdown">
        {categories.length === 0 ? (
          <EmptyState title="No categorised debits in range" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
                <tr className="border-b border-line">
                  <th className="py-2 text-left">Category</th>
                  <th className="py-2 text-right">Transactions</th>
                  <th className="py-2 text-right">Total spend</th>
                  <th className="py-2 text-right">Avg / txn</th>
                </tr>
              </thead>
              <tbody>
                {categories.map((c) => (
                  <tr key={c.category} className="border-b border-line/60">
                    <td className="py-2 text-slate-100">{c.category}</td>
                    <td className="py-2 text-right text-slate-300 tabular">{c.count}</td>
                    <td className="py-2 text-right text-loss-400 font-medium tabular">
                      {inr(c.total, true)}
                    </td>
                    <td className="py-2 text-right text-slate-400 tabular">
                      {inr(c.total / Math.max(c.count, 1), true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Top merchants">
        {top_merchants.length === 0 ? (
          <EmptyState title="No merchants in range" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
                <tr className="border-b border-line">
                  <th className="py-2 text-left">Merchant</th>
                  <th className="py-2 text-right">Transactions</th>
                  <th className="py-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {top_merchants.map((m) => (
                  <tr key={m.counterparty} className="border-b border-line/60">
                    <td className="py-2 text-slate-100">{m.counterparty}</td>
                    <td className="py-2 text-right text-slate-300 tabular">{m.count}</td>
                    <td className="py-2 text-right text-loss-400 font-medium tabular">
                      {inr(m.total, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
