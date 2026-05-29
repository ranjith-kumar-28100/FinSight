import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { getForecast } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { compactInr, inr, shortMonth } from "@/lib/format";

export function ForecastPage() {
  const { start, end } = useDateRange();
  const [horizon, setHorizon] = useState(3);

  const q = useQuery({
    queryKey: ["forecast", horizon, start, end],
    queryFn: () => getForecast(horizon, start, end),
    enabled: start !== null && end !== null,
  });

  if (q.isLoading) return <Spinner />;

  if (!q.data || q.data.history.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No history in this range"
          description="Upload a bank statement or widen the date filter to give the forecast model a baseline."
        />
      </Card>
    );
  }

  const chartData = [
    ...q.data.history.map((m) => ({
      month: shortMonth(m.month),
      historical: Number(m.net_savings),
    })),
    ...q.data.projections.map((p) => ({
      month: shortMonth(p.month),
      forecast: Number(p.savings_mid),
      range: [Number(p.savings_low), Number(p.savings_high)],
    })),
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-50">Forecast</h1>
          <p className="mt-1 text-sm text-slate-400">
            Projects net savings from the {start} → {end} baseline forward by {horizon} months.
          </p>
        </div>
        <label className="text-xs text-slate-300">
          Horizon (months)
          <input
            type="number"
            min={1}
            max={12}
            value={horizon}
            onChange={(e) => setHorizon(Math.max(1, Math.min(12, Number(e.target.value) || 3)))}
            className="ml-2 w-16 rounded-lg border border-line bg-ink-800/80 px-2 py-1 text-xs text-slate-100"
          />
        </label>
      </div>

      <Card title="Savings projection" subtitle="Solid = historical · Dashed = forecast mid · Shaded = low/high band">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
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
                formatter={(v) => (Array.isArray(v) ? `${inr(v[0])} – ${inr(v[1])}` : inr(v as number))}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area
                type="monotone"
                dataKey="range"
                name="Forecast band"
                fill="rgba(192, 132, 252, 0.18)"
                stroke="rgba(192, 132, 252, 0.4)"
              />
              <Line
                type="monotone"
                dataKey="historical"
                name="Historical"
                stroke="#818cf8"
                strokeWidth={2.5}
                dot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="forecast"
                name="Forecast (mid)"
                stroke="#c084fc"
                strokeDasharray="6 3"
                strokeWidth={2.5}
                dot={{ r: 4 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title="Projected months" bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
              <tr className="border-b border-line">
                <th className="py-2 pl-4 text-left">Month</th>
                <th className="py-2 text-right">Income (mid)</th>
                <th className="py-2 text-right">Fixed</th>
                <th className="py-2 text-right">Discretionary</th>
                <th className="py-2 text-right">Savings low</th>
                <th className="py-2 text-right">Savings mid</th>
                <th className="py-2 pr-4 text-right">Savings high</th>
              </tr>
            </thead>
            <tbody>
              {q.data.projections.map((p) => (
                <tr key={p.month} className="border-b border-line/60">
                  <td className="py-2 pl-4 text-slate-100 font-medium">
                    {shortMonth(p.month)}
                  </td>
                  <td className="py-2 text-right text-slate-300 tabular">{inr(p.income_mid)}</td>
                  <td className="py-2 text-right text-slate-300 tabular">{inr(p.fixed)}</td>
                  <td className="py-2 text-right text-slate-300 tabular">{inr(p.discretionary_mid)}</td>
                  <td className="py-2 text-right text-slate-400 tabular">{inr(p.savings_low)}</td>
                  <td className="py-2 text-right text-brand-300 font-semibold tabular">{inr(p.savings_mid)}</td>
                  <td className="py-2 pr-4 text-right text-gain-400 tabular">{inr(p.savings_high)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
