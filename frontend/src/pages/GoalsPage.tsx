import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Lightbulb, Target, XCircle } from "lucide-react";
import clsx from "clsx";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { assessGoal, getInsights, whatIf } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";
import { compactInr, inr } from "@/lib/format";

export function GoalsPage() {
  const { start, end } = useDateRange();
  const [target, setTarget] = useState("500000");
  const [horizon, setHorizon] = useState(10);
  const [description, setDescription] = useState("");

  const insightsQ = useQuery({
    queryKey: ["insights-goal", start, end],
    queryFn: () => getInsights(start, end),
    enabled: start !== null && end !== null,
  });

  const assess = useMutation({
    mutationFn: () =>
      assessGoal({
        target_amount: Number(target.replace(/,/g, "")),
        horizon_months: horizon,
        description,
        start,
        end,
      }),
  });

  // What-if state — keyed by category
  const [adjustments, setAdjustments] = useState<Record<string, number>>({});
  const whatIfM = useMutation({
    mutationFn: () =>
      whatIf({
        target_amount: Number(target.replace(/,/g, "")),
        horizon_months: horizon,
        adjustments,
        start,
        end,
      }),
  });

  const months = insightsQ.data?.monthly_maps.length || 1;
  const topCats = (insightsQ.data?.categories ?? []).slice(0, 8);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50">Goals</h1>
        <p className="mt-1 text-sm text-slate-400">
          Pick a target and horizon; FinSight checks feasibility against your
          {" "}
          {start} → {end} baseline and suggests adjustments.
        </p>
      </div>

      <Card title="Set your goal">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label className="label">Target Amount (₹)</label>
            <input
              className="input tabular"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Horizon (months)</label>
            <input
              type="number"
              min={1}
              max={120}
              className="input tabular"
              value={horizon}
              onChange={(e) => setHorizon(Math.max(1, Number(e.target.value) || 10))}
            />
          </div>
          <div>
            <label className="label">Description (optional)</label>
            <input
              className="input"
              placeholder="e.g. Emergency fund"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            className="btn-primary"
            disabled={assess.isPending}
            onClick={() => assess.mutate()}
          >
            <Target className="h-4 w-4" />
            {assess.isPending ? "Assessing…" : "Assess Feasibility"}
          </button>
        </div>
      </Card>

      {assess.isError && (
        <Card>
          <p className="text-sm text-loss-400">Couldn't assess: {(assess.error as any)?.message}</p>
        </Card>
      )}

      {assess.data && (
        <Card>
          <VerdictRow
            verdict={assess.data.verdict}
            required={Number(assess.data.required_monthly)}
            forecast={Number(assess.data.forecast_monthly)}
            gap={Number(assess.data.gap)}
          />
          {assess.data.suggestions.length > 0 && (
            <div className="mt-5 space-y-2">
              <p className="text-sm font-semibold text-slate-200 flex items-center gap-1.5">
                <Lightbulb className="h-4 w-4 text-gold-400" />
                Suggested actions
              </p>
              <ul className="space-y-2">
                {assess.data.suggestions.map((s, i) => (
                  <li key={i} className="rounded-xl border border-line bg-surface px-4 py-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium text-slate-100">
                        {s.action || s.category}
                      </span>
                      <span className="text-xs text-slate-400">
                        Save ~{inr(s.saving_amount ?? 0)}/mo · {(s.reduction_pct ?? 0).toFixed(0)}%
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-slate-400">{s.rationale}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

      <Card
        title="What-if simulator"
        subtitle="Adjust your top categories to see how your savings gap changes — no LLM call, just code arithmetic."
      >
        {insightsQ.isLoading ? (
          <Spinner />
        ) : topCats.length === 0 ? (
          <EmptyState title="No category data in this range" />
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              {topCats.map((c) => {
                const avg = c.total / months;
                const current = adjustments[c.category] ?? Math.round(avg);
                const maxV = Math.max(1000, Math.round(avg * 2 + 1000));
                return (
                  <div key={c.category}>
                    <div className="flex items-baseline justify-between text-xs">
                      <span className="text-slate-200 font-medium">{c.category}</span>
                      <span className="text-slate-400 tabular">
                        {inr(current)}/mo
                        <span className="ml-2 text-slate-500">
                          (avg {compactInr(avg)})
                        </span>
                      </span>
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={maxV}
                      step={500}
                      value={current}
                      onChange={(e) =>
                        setAdjustments({
                          ...adjustments,
                          [c.category]: Number(e.target.value),
                        })
                      }
                      className="mt-2 w-full accent-brand-500"
                    />
                  </div>
                );
              })}
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-end gap-3">
              <button
                className="btn-ghost"
                onClick={() => setAdjustments({})}
                disabled={Object.keys(adjustments).length === 0}
              >
                Reset
              </button>
              <button
                className="btn-primary"
                disabled={whatIfM.isPending}
                onClick={() => whatIfM.mutate()}
              >
                Simulate
              </button>
            </div>

            {whatIfM.data && (
              <div className="mt-5">
                <VerdictRow
                  verdict={whatIfM.data.verdict}
                  required={Number(whatIfM.data.required_monthly)}
                  forecast={Number(whatIfM.data.adjusted_savings)}
                  gap={Number(whatIfM.data.gap)}
                  forecastLabel="Adjusted Savings/mo"
                />
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

function VerdictRow({
  verdict,
  required,
  forecast,
  gap,
  forecastLabel = "Forecast/mo",
}: {
  verdict: "on_track" | "shortfall" | "surplus";
  required: number;
  forecast: number;
  gap: number;
  forecastLabel?: string;
}) {
  const Icon = verdict === "shortfall" ? XCircle : CheckCircle2;
  const tone =
    verdict === "shortfall"
      ? "from-loss-500/20 to-loss-500/5 border-loss-500/30 text-loss-400"
      : "from-gain-500/20 to-gain-500/5 border-gain-500/30 text-gain-400";

  return (
    <div className={clsx("flex flex-wrap items-center gap-4 rounded-2xl border bg-gradient-to-r px-4 py-3", tone)}>
      <div className="flex items-center gap-2">
        <Icon className="h-5 w-5" />
        <span className="font-semibold">
          {verdict === "shortfall"
            ? `Shortfall of ${inr(gap)}/mo`
            : verdict === "surplus"
            ? `Surplus of ${inr(Math.abs(gap))}/mo`
            : "On track"}
        </span>
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-slate-300">
        <span>
          Required/mo: <span className="tabular text-slate-100">{inr(required)}</span>
        </span>
        <span>
          {forecastLabel}: <span className="tabular text-slate-100">{inr(forecast)}</span>
        </span>
      </div>
    </div>
  );
}
