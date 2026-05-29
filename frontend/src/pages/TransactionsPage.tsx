import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { Filter, Link2, Receipt, RefreshCw, Repeat, Search } from "lucide-react";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import {
  getOrphans,
  getWalletDetail,
  listTransactions,
} from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { inr, shortDate } from "@/lib/format";
import type { Transaction } from "@/types";

type DirectionFilter = "all" | "debit" | "credit";
type SourceFilter = "bank" | "gpay" | "paytm" | "all";

export function TransactionsPage() {
  const { start, end } = useDateRange();
  const [direction, setDirection] = useState<DirectionFilter>("all");
  const [source, setSource] = useState<SourceFilter>("bank");
  const [needsReview, setNeedsReview] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedBank, setSelectedBank] = useState<Transaction | null>(null);

  const txnsQ = useQuery({
    queryKey: ["transactions", start, end, direction, source, needsReview],
    queryFn: () =>
      listTransactions({
        start,
        end,
        direction: direction === "all" ? undefined : direction,
        source: source === "all" ? undefined : source,
        needs_review: needsReview ? true : undefined,
        limit: 1000,
      }),
    enabled: start !== null && end !== null,
  });

  const orphansQ = useQuery({ queryKey: ["orphans"], queryFn: getOrphans });

  const walletQ = useQuery({
    queryKey: ["wallet-detail", selectedBank?.txn_id],
    queryFn: () => getWalletDetail(selectedBank!.txn_id),
    enabled: !!selectedBank,
  });

  const filtered = useMemo(() => {
    if (!txnsQ.data) return [];
    if (!search.trim()) return txnsQ.data.transactions;
    const q = search.toLowerCase();
    return txnsQ.data.transactions.filter(
      (t) =>
        t.merchant.toLowerCase().includes(q) ||
        t.raw_description.toLowerCase().includes(q) ||
        (t.category ?? "").toLowerCase().includes(q)
    );
  }, [txnsQ.data, search]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-50">Transactions</h1>
          <p className="mt-1 text-sm text-slate-400">
            Source filter defaults to <span className="text-slate-300">Bank</span>.
            Click any bank row to see its wallet drill-down.
          </p>
        </div>
        <button
          onClick={() => txnsQ.refetch()}
          className="btn-ghost"
          disabled={txnsQ.isFetching}
        >
          <RefreshCw className={clsx("h-3.5 w-3.5", txnsQ.isFetching && "animate-spin")} />
          Refresh
        </button>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              className="input pl-9"
              placeholder="Search merchant, description, category…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Select
            label="Direction"
            value={direction}
            options={[
              { value: "all", label: "All" },
              { value: "debit", label: "Debit" },
              { value: "credit", label: "Credit" },
            ]}
            onChange={(v) => setDirection(v as DirectionFilter)}
          />
          <Select
            label="Source"
            value={source}
            options={[
              { value: "bank", label: "Bank (HDFC)" },
              { value: "gpay", label: "GPay" },
              { value: "paytm", label: "Paytm" },
              { value: "all", label: "All" },
            ]}
            onChange={(v) => setSource(v as SourceFilter)}
          />
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input
              type="checkbox"
              checked={needsReview}
              onChange={(e) => setNeedsReview(e.target.checked)}
              className="h-3.5 w-3.5 accent-brand-500"
            />
            Needs review only
          </label>
        </div>
      </Card>

      {txnsQ.isLoading ? (
        <Spinner />
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState title="No transactions match the current filters" />
        </Card>
      ) : (
        <Card
          title={`${filtered.length.toLocaleString()} transactions`}
          subtitle="Click a row to expand wallet detail (when available)."
          bodyClassName="p-0"
        >
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-ink-900/90 backdrop-blur-xl text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                <tr className="border-b border-line">
                  <th className="py-2 pl-4 text-left">Date</th>
                  <th className="py-2 text-left">Merchant</th>
                  <th className="py-2 text-left">Category</th>
                  <th className="py-2 text-right">Amount</th>
                  <th className="py-2 text-center pr-4">Flags</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr
                    key={t.txn_id}
                    onClick={() => t.source === "bank" && setSelectedBank(t)}
                    className={clsx(
                      "border-b border-line/60 transition hover:bg-surface-strong",
                      t.source === "bank" && "cursor-pointer",
                      selectedBank?.txn_id === t.txn_id && "bg-brand-500/10"
                    )}
                  >
                    <td className="py-2 pl-4 text-slate-300 tabular whitespace-nowrap">
                      {shortDate(t.date)}
                    </td>
                    <td className="py-2 pr-2">
                      <div className="flex items-center gap-2">
                        <span className="text-slate-100">
                          {t.merchant || t.raw_description.slice(0, 32)}
                        </span>
                        {t.enriched_counterparty && (
                          <Link2
                            className="h-3 w-3 text-gain-400"
                            aria-label="Enriched from wallet"
                          />
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 truncate max-w-[42ch]">
                        {t.raw_description}
                      </div>
                    </td>
                    <td className="py-2 pr-2 text-slate-400">{t.category || "—"}</td>
                    <td
                      className={clsx(
                        "py-2 pr-2 text-right font-medium tabular",
                        t.direction === "credit" ? "text-gain-400" : "text-loss-400"
                      )}
                    >
                      {t.direction === "credit" ? "+" : "−"}
                      {inr(t.amount, true)}
                    </td>
                    <td className="py-2 pr-4 text-center">
                      <div className="inline-flex items-center gap-1">
                        {t.is_recurring && (
                          <span title="Recurring">
                            <Repeat className="h-3.5 w-3.5 text-brand-400" />
                          </span>
                        )}
                        {t.needs_review && (
                          <span className="chip-gold !py-0">!</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Wallet drill-down */}
      {selectedBank && (
        <Card
          title="Wallet Detail"
          subtitle={`Linked GPay/Paytm rows for ${shortDate(selectedBank.date)} · ${inr(selectedBank.amount, true)}`}
          actions={
            <button onClick={() => setSelectedBank(null)} className="btn-ghost !py-1 !px-2 text-xs">
              Close
            </button>
          }
        >
          {walletQ.isLoading ? (
            <Spinner />
          ) : (walletQ.data?.transactions.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-400">
              No wallet record linked to this bank transaction.
            </p>
          ) : (
            <ul className="divide-y divide-line">
              {walletQ.data!.transactions.map((w) => (
                <li key={w.txn_id} className="py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium text-slate-100">{w.counterparty}</span>
                    <span className="text-xs text-slate-400">
                      {w.source.toUpperCase()} · {shortDate(w.date)} · {inr(w.amount, true)}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{w.raw_description}</p>
                  {w.source_ref && (
                    <p className="mt-0.5 font-mono text-[11px] text-slate-500">
                      UPI ref: {w.source_ref}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {/* Orphan wallet section */}
      <Card
        title={
          <span className="flex items-center gap-2">
            <Receipt className="h-4 w-4 text-slate-400" />
            Orphan wallet records ({orphansQ.data?.count ?? 0})
          </span>
        }
        subtitle="Wallet rows with no bank counterpart — never included in totals."
      >
        {orphansQ.isLoading ? (
          <Spinner />
        ) : (orphansQ.data?.count ?? 0) === 0 ? (
          <p className="text-sm text-slate-400">No orphan wallet rows.</p>
        ) : (
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-ink-900/90 text-[10px] uppercase tracking-[0.14em] text-slate-400">
                <tr className="border-b border-line">
                  <th className="py-2 text-left">Date</th>
                  <th className="py-2 text-left">Source</th>
                  <th className="py-2 text-left">Counterparty</th>
                  <th className="py-2 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {orphansQ.data!.transactions.slice(0, 200).map((t) => (
                  <tr key={t.txn_id} className="border-b border-line/60">
                    <td className="py-2 text-slate-300 tabular">{shortDate(t.date)}</td>
                    <td className="py-2 text-slate-500">{t.source.toUpperCase()}</td>
                    <td className="py-2 text-slate-200">{t.counterparty}</td>
                    <td
                      className={clsx(
                        "py-2 text-right font-medium tabular",
                        t.direction === "credit" ? "text-gain-400" : "text-loss-400"
                      )}
                    >
                      {inr(t.amount, true)}
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

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="text-xs">
      <span className="mr-1.5 text-slate-400">
        <Filter className="inline h-3 w-3 mr-0.5" />
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-line bg-ink-800/80 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-brand-500"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
