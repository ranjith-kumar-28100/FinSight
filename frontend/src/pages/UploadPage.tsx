import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  CloudUpload,
  FileText,
  Loader2,
  Sparkles,
  Trash2,
  Wallet,
} from "lucide-react";
import clsx from "clsx";

import { Card } from "@/components/Card";
import { clearAllData, runPipeline } from "@/api/endpoints";
import type { PipelineResponse } from "@/types";

interface SlotState {
  file: File | null;
}

const ACCEPT = {
  hdfc: ".xls,.xlsx",
  gpay: ".pdf",
  paytm: ".xlsx",
};

const SLOTS: { key: keyof typeof ACCEPT; label: string; hint: string; icon: any }[] = [
  { key: "hdfc", label: "HDFC Bank", hint: "Source of truth · XLS/XLSX", icon: Wallet },
  { key: "gpay", label: "Google Pay", hint: "PDF from Google Takeout", icon: FileText },
  { key: "paytm", label: "Paytm Wallet", hint: "XLSX passbook export", icon: FileText },
];

export function UploadPage() {
  const queryClient = useQueryClient();
  const [slots, setSlots] = useState<Record<string, SlotState>>({
    hdfc: { file: null },
    gpay: { file: null },
    paytm: { file: null },
  });
  const [result, setResult] = useState<PipelineResponse | null>(null);

  const upload = useMutation({
    mutationFn: () =>
      runPipeline({
        hdfc: slots.hdfc.file ?? undefined,
        gpay: slots.gpay.file ?? undefined,
        paytm: slots.paytm.file ?? undefined,
      }),
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries();
    },
  });

  const clear = useMutation({
    mutationFn: () => clearAllData(),
    onSuccess: () => {
      setResult(null);
      setSlots({ hdfc: { file: null }, gpay: { file: null }, paytm: { file: null } });
      queryClient.invalidateQueries();
    },
  });

  const hasAny = Object.values(slots).some((s) => s.file);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50">Upload statements</h1>
        <p className="mt-1 text-sm text-slate-400">
          The HDFC bank statement drives every total. GPay / Paytm files are
          used purely to enrich UPI merchant names — they never inflate your
          numbers.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {SLOTS.map((s) => {
          const Icon = s.icon;
          const slot = slots[s.key];
          return (
            <Card key={s.key}>
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500/10 text-brand-400">
                  <Icon className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <p className="font-medium text-slate-100">{s.label}</p>
                  <p className="text-xs text-slate-500">{s.hint}</p>
                </div>
              </div>

              <label
                className={clsx(
                  "mt-4 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-line bg-ink-900/40 px-4 py-6 transition hover:border-brand-500/40 hover:bg-surface-strong",
                  slot.file && "border-gain-500/40 bg-gain-500/5"
                )}
              >
                <CloudUpload className="h-5 w-5 text-brand-400" />
                <p className="text-xs text-slate-300">
                  {slot.file ? slot.file.name : "Click to choose file"}
                </p>
                <input
                  type="file"
                  accept={ACCEPT[s.key]}
                  className="sr-only"
                  onChange={(e) =>
                    setSlots({
                      ...slots,
                      [s.key]: { file: e.target.files?.[0] ?? null },
                    })
                  }
                />
              </label>
              {slot.file && (
                <button
                  className="mt-2 text-xs text-slate-400 hover:text-slate-200"
                  onClick={() => setSlots({ ...slots, [s.key]: { file: null } })}
                >
                  Remove
                </button>
              )}
            </Card>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          className="btn-danger"
          disabled={clear.isPending}
          onClick={() => {
            if (confirm("Wipe all transactions and derived tables?")) clear.mutate();
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Clear all data
        </button>
        <button
          className="btn-primary"
          disabled={!hasAny || upload.isPending}
          onClick={() => upload.mutate()}
        >
          {upload.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Running pipeline…
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              Process Statements
            </>
          )}
        </button>
      </div>

      {upload.isError && (
        <Card>
          <p className="text-sm text-loss-400">
            Pipeline failed: {(upload.error as any)?.response?.data?.detail ?? (upload.error as any)?.message}
          </p>
        </Card>
      )}

      {result && (
        <Card title="Pipeline summary">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            <Stat label="Parsed" value={result.ingestion.total_parsed ?? 0} />
            <Stat label="Inserted" value={result.ingestion.inserted ?? 0} />
            <Stat label="Linked" value={result.reconciliation.auto_linked ?? 0} />
            <Stat label="Enriched" value={result.reconciliation.enriched ?? 0} />
            <Stat label="Categorised" value={result.categorisation.categorised ?? 0} />
            <Stat label="Bank rules" value={result.categorisation.bank_rule_matched ?? 0} />
            <Stat label="LLM calls" value={result.categorisation.bank_llm_calls ?? 0} />
            <Stat label="Recurring series" value={result.recurring.series_found ?? 0} />
            <Stat label="Months" value={result.analytics.months_computed ?? 0} />
            <Stat label="Flagged" value={result.anomaly.flagged ?? 0} />
          </div>
          {result.errors.length > 0 && (
            <div className="mt-4 rounded-xl border border-loss-500/30 bg-loss-500/5 p-3 text-xs text-loss-300">
              <p className="font-semibold">Warnings</p>
              <ul className="mt-1 list-disc pl-4">
                {result.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-4 flex items-center gap-2 text-sm text-gain-400">
            <CheckCircle2 className="h-4 w-4" />
            Pipeline complete — dashboard refreshed.
          </div>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-3">
      <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">{label}</p>
      <p className="text-lg font-semibold tabular text-slate-100">{value}</p>
    </div>
  );
}
