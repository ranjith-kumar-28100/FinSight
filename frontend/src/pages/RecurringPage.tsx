import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Banknote,
  Clapperboard,
  CreditCard,
  Home,
  Plug,
  Shield,
  TrendingUp,
} from "lucide-react";
import { LucideIcon } from "lucide-react";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { getRecurring } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { inr } from "@/lib/format";

const GROUPS: { key: string; label: string; icon: LucideIcon }[] = [
  { key: "emi", label: "EMI / Loans", icon: CreditCard },
  { key: "sip", label: "SIP / Investments", icon: TrendingUp },
  { key: "insurance", label: "Insurance", icon: Shield },
  { key: "rent", label: "Rent & Housing", icon: Home },
  { key: "utility", label: "Utilities", icon: Plug },
  { key: "subscription", label: "Subscriptions", icon: Clapperboard },
  { key: "other", label: "Other Recurring", icon: Banknote },
];

export function RecurringPage() {
  const { start, end } = useDateRange();
  const q = useQuery({
    queryKey: ["recurring", start, end],
    queryFn: () => getRecurring(start, end),
    enabled: start !== null && end !== null,
  });

  const grouped = useMemo(() => {
    const out = new Map<string, typeof q.data>();
    (q.data ?? []).forEach((s) => {
      const k = s.recurring_type || "other";
      const arr = out.get(k) ?? [];
      arr.push(s);
      out.set(k, arr);
    });
    return out;
  }, [q.data]);

  const fixedMonthly = (q.data ?? [])
    .filter((s) =>
      ["emi", "sip", "insurance", "rent", "utility"].includes(s.recurring_type ?? "")
    )
    .reduce((acc, s) => acc + Number(s.avg_amount), 0);

  if (q.isLoading) return <Spinner />;
  if (!q.data || q.data.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No recurring series in this range"
          description="Series with at least one occurrence between the selected dates will appear here."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-50">Recurring</h1>
          <p className="mt-1 text-sm text-slate-400">
            EMIs, SIPs, subscriptions and other repeat charges active in {start} → {end}.
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] uppercase tracking-[0.14em] text-slate-400">
            Est. fixed monthly
          </p>
          <p className="text-2xl font-semibold tabular text-slate-100">
            {inr(fixedMonthly)}
          </p>
        </div>
      </div>

      <div className="space-y-4">
        {GROUPS.map(({ key, label, icon: Icon }) => {
          const series = grouped.get(key);
          if (!series || series.length === 0) return null;
          return (
            <Card
              key={key}
              title={
                <span className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-brand-400" />
                  {label}{" "}
                  <span className="text-slate-500">({series.length})</span>
                </span>
              }
              bodyClassName="p-0"
            >
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-[10px] uppercase tracking-[0.14em] text-slate-400">
                    <tr className="border-b border-line">
                      <th className="py-2 pl-4 text-left">Counterparty</th>
                      <th className="py-2 text-left">Category</th>
                      <th className="py-2 text-right">Avg amount</th>
                      <th className="py-2 text-left">Cadence</th>
                      <th className="py-2 text-left">First seen</th>
                      <th className="py-2 text-left">Last seen</th>
                      <th className="py-2 pr-4 text-right">Transactions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {series
                      .slice()
                      .sort((a, b) => Number(b.avg_amount) - Number(a.avg_amount))
                      .map((s) => (
                        <tr key={s.series_id} className="border-b border-line/60">
                          <td className="py-2 pl-4 text-slate-100">{s.counterparty}</td>
                          <td className="py-2 text-slate-400">{s.category}</td>
                          <td className="py-2 text-right text-loss-400 font-medium tabular">
                            {inr(s.avg_amount)}
                          </td>
                          <td className="py-2 text-slate-300">{s.cadence}</td>
                          <td className="py-2 text-slate-400">{s.first_seen || "—"}</td>
                          <td className="py-2 text-slate-400">{s.last_seen || "—"}</td>
                          <td className="py-2 pr-4 text-right text-slate-300 tabular">
                            {s.txn_count}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
