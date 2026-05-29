import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowDown,
  ArrowUp,
  Coins,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { Spinner } from "@/components/Spinner";
import { getHealth, getInsights } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { compactInr, inr, pct, shortMonth } from "@/lib/format";

const PALETTE = [
  "#6366f1",
  "#10b981",
  "#f59e0b",
  "#06b6d4",
  "#ef4444",
  "#a855f7",
  "#22d3ee",
  "#84cc16",
  "#f472b6",
  "#fbbf24",
];

export function DashboardPage() {
  const { start, end } = useDateRange();
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth });
  const insights = useQuery({
    queryKey: ["insights", start, end],
    queryFn: () => getInsights(start, end),
    enabled: start !== null && end !== null,
  });

  // If the query is actively loading (enabled and in-flight), show spinner.
  // But if the query is disabled (start/end are null because DB is empty),
  // fall through to render the empty-state UI instead of spinning forever.
  const queryDisabled = start === null || end === null;
  if (insights.isLoading) return <Spinner label="Loading insights…" />;

  const hasData = !queryDisabled && !!insights.data && (health.data?.bank_transactions ?? 0) > 0;

  const totals = insights.data?.totals ?? { income: 0, expense: 0, net: 0 };
  const categories = insights.data?.categories ?? [];
  const top_merchants = insights.data?.top_merchants ?? [];
  const monthly_maps = insights.data?.monthly_maps ?? [];
  const savingsRate = totals.income > 0 ? totals.net / totals.income : 0;

  // Monthly trend data — derived from maps.
  const monthlyTrend = monthly_maps.map((m) => ({
    month: shortMonth(m.month),
    income: Number(m.income),
    spend: Number(m.total_spend),
    savings: Number(m.net_savings),
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-50">Dashboard</h1>
          <p className="mt-1 text-sm text-slate-400">
            Overview — {start} → {end}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {health.data?.enriched_pct !== undefined && (
            <span className="chip-gold">
              <Sparkles className="h-3 w-3" />
              {pct(health.data.enriched_pct)} merchants enriched
            </span>
          )}
          {(health.data?.orphan_wallet ?? 0) > 0 && (
            <span className="chip">
              {health.data!.orphan_wallet} orphan wallet rows
            </span>
          )}
        </div>
      </div>

      {!hasData ? (
        <Card>
          <EmptyState
            title="No data yet"
            description="Upload an HDFC bank statement (and optionally GPay / Paytm exports) to bring this dashboard to life."
            action={
              <a href="/upload" className="btn-primary">
                <Wallet className="h-4 w-4" /> Go to Upload
              </a>
            }
          />
        </Card>
      ) : (
        <>
          {/* KPI Row */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Income"
              value={inr(totals.income)}
              tone="gain"
              icon={ArrowDown}
            />
            <KpiCard
              label="Expenses"
              value={inr(totals.expense)}
              tone="loss"
              icon={ArrowUp}
            />
            <KpiCard
              label="Net"
              value={inr(totals.net)}
              tone={totals.net >= 0 ? "gain" : "loss"}
              icon={Coins}
              deltaLabel={totals.net >= 0 ? "Surplus" : "Deficit"}
            />
            <KpiCard
              label="Savings Rate"
              value={pct(savingsRate)}
              tone={savingsRate >= 0.2 ? "gain" : savingsRate >= 0 ? "gold" : "loss"}
              icon={TrendingUp}
            />
          </div>

          {/* Trend chart */}
          {monthlyTrend.length > 0 && (
            <Card title="Monthly trend" subtitle="Income · Spend · Net savings">
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monthlyTrend}>
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
                    <Line
                      type="monotone"
                      dataKey="income"
                      stroke="#10b981"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="spend"
                      stroke="#ef4444"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="savings"
                      stroke="#818cf8"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Category pie */}
            <Card title="Spending by category">
              {categories.length === 0 ? (
                <EmptyState title="No category spend in range" />
              ) : (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={categories.slice(0, 10)}
                        dataKey="total"
                        nameKey="category"
                        innerRadius={60}
                        outerRadius={100}
                        paddingAngle={2}
                      >
                        {categories.slice(0, 10).map((_, i) => (
                          <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          background: "#0f172a",
                          border: "1px solid rgba(148,163,184,0.18)",
                          borderRadius: 10,
                          fontSize: 12,
                        }}
                        formatter={(v) => inr(v as number)}
                      />
                      <Legend
                        verticalAlign="bottom"
                        height={36}
                        wrapperStyle={{ fontSize: 11 }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>

            {/* Top merchants */}
            <Card title="Top merchants">
              {top_merchants.length === 0 ? (
                <EmptyState title="No merchants in range" />
              ) : (
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={top_merchants.slice(0, 10).map((m) => ({
                        name: m.counterparty.slice(0, 20),
                        total: m.total,
                      }))}
                      layout="vertical"
                      margin={{ left: 10 }}
                    >
                      <CartesianGrid stroke="rgba(148,163,184,0.08)" horizontal={false} />
                      <XAxis
                        type="number"
                        stroke="#94a3b8"
                        tick={{ fontSize: 11 }}
                        tickFormatter={(v) => compactInr(v as number)}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        stroke="#94a3b8"
                        tick={{ fontSize: 11 }}
                        width={110}
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
                      <Bar dataKey="total" radius={[0, 6, 6, 0]} fill="#6366f1" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
