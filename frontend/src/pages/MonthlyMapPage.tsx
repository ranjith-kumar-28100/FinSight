import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  ComposedChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import clsx from "clsx";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { getCategoryHeatmap, getMonthlyMaps } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { compactInr, inr, shortMonth } from "@/lib/format";

export function MonthlyMapPage() {
  const { start, end } = useDateRange();

  const mapsQ = useQuery({
    queryKey: ["monthly-maps", start, end],
    queryFn: () => getMonthlyMaps(start, end),
    enabled: start !== null && end !== null,
  });
  const heatQ = useQuery({
    queryKey: ["category-heatmap", start, end],
    queryFn: () => getCategoryHeatmap(start, end),
    enabled: start !== null && end !== null,
  });

  if (mapsQ.isLoading) return <Spinner />;

  if (!mapsQ.data || mapsQ.data.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No transactions in this range"
          description="Upload a bank statement or widen the date filter to see monthly aggregates."
        />
      </Card>
    );
  }

  const data = mapsQ.data.map((m) => ({
    month: shortMonth(m.month),
    income: Number(m.income),
    fixed: Number(m.fixed_obligations),
    discretionary: Number(m.discretionary),
    savings: Number(m.net_savings),
  }));

  // Heatmap pivot
  const months = Array.from(new Set(heatQ.data?.map((c) => c.month) ?? [])).sort();
  const cats = Array.from(new Set(heatQ.data?.map((c) => c.category) ?? []));
  const cellByKey = new Map<string, number>();
  heatQ.data?.forEach((c) => cellByKey.set(`${c.month}|${c.category}`, c.total));
  const heatMax = Math.max(1, ...Array.from(cellByKey.values()));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50">Monthly Money Map</h1>
        <p className="mt-1 text-sm text-slate-400">
          Per-month income, fixed obligations, discretionary spend, net savings —
          recomputed for {start} → {end}.
        </p>
      </div>

      <Card title="Cashflow composition">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} stackOffset="sign">
              <CartesianGrid stroke="rgba(148,163,184,0.08)" />
              <XAxis dataKey="month" stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis
                stroke="#94a3b8"
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => compactInr(v as number)}
              />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid rgba(148,163,184,0.18)",
                  borderRadius: 10,
                  fontSize: 12,
                }}
                formatter={(v) => inr(v as number)}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="fixed" name="Fixed obligations" stackId="spend" fill="#ef4444" />
              <Bar dataKey="discretionary" name="Discretionary" stackId="spend" fill="#f59e0b" />
              <Bar dataKey="savings" name="Net savings" stackId="spend" fill="#10b981" />
              <Line
                type="monotone"
                dataKey="income"
                name="Income"
                stroke="#818cf8"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Per-month summary" bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
              <tr className="border-b border-line">
                <th className="py-2 pl-4 text-left">Month</th>
                <th className="py-2 text-right">Income</th>
                <th className="py-2 text-right">Spend</th>
                <th className="py-2 text-right">Fixed</th>
                <th className="py-2 text-right">Discretionary</th>
                <th className="py-2 text-right">Net Savings</th>
                <th className="py-2 text-right pr-4">Savings Rate</th>
              </tr>
            </thead>
            <tbody>
              {mapsQ.data.map((m) => {
                const net = Number(m.net_savings);
                return (
                  <tr key={m.month} className="border-b border-line/60">
                    <td className="py-2 pl-4 font-medium text-slate-100">
                      {shortMonth(m.month)}
                    </td>
                    <td className="py-2 text-right text-gain-400 tabular">{inr(m.income)}</td>
                    <td className="py-2 text-right text-loss-400 tabular">{inr(m.total_spend)}</td>
                    <td className="py-2 text-right text-slate-300 tabular">{inr(m.fixed_obligations)}</td>
                    <td className="py-2 text-right text-slate-300 tabular">{inr(m.discretionary)}</td>
                    <td
                      className={clsx(
                        "py-2 text-right tabular font-semibold",
                        net >= 0 ? "text-gain-400" : "text-loss-400"
                      )}
                    >
                      {inr(net)}
                    </td>
                    <td className="py-2 pr-4 text-right text-slate-300 tabular">
                      {(Number(m.savings_rate) * 100).toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {cats.length > 0 && months.length > 0 && (
        <Card
          title="Category × month heatmap"
          subtitle="Darker = more spend. Hover any cell for the exact figure."
        >
          <div className="overflow-x-auto">
            <table className="border-separate border-spacing-1 text-xs">
              <thead>
                <tr>
                  <th></th>
                  {months.map((m) => (
                    <th key={m} className="px-2 py-1 text-slate-400 font-medium">
                      {shortMonth(m)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cats.map((cat) => (
                  <tr key={cat}>
                    <td className="pr-3 text-right text-slate-300">{cat}</td>
                    {months.map((m) => {
                      const v = cellByKey.get(`${m}|${cat}`) ?? 0;
                      const intensity = v / heatMax;
                      return (
                        <td
                          key={m}
                          title={`${cat} · ${shortMonth(m)} · ${inr(v)}`}
                          className="h-9 w-20 rounded-md tabular text-center text-[10px]"
                          style={{
                            backgroundColor: `rgba(99,102,241,${0.06 + intensity * 0.6})`,
                            color: intensity > 0.6 ? "#fff" : "#cbd5e1",
                          }}
                        >
                          {v > 0 ? compactInr(v) : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
