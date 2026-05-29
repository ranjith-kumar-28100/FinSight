import clsx from "clsx";
import { LucideIcon, TrendingDown, TrendingUp } from "lucide-react";

interface KpiCardProps {
  label: string;
  value: string;
  delta?: number;
  deltaLabel?: string;
  icon?: LucideIcon;
  tone?: "neutral" | "gain" | "loss" | "gold";
}

const toneRing: Record<NonNullable<KpiCardProps["tone"]>, string> = {
  neutral: "ring-brand-500/20",
  gain: "ring-gain-500/25",
  loss: "ring-loss-500/25",
  gold: "ring-gold-500/25",
};
const toneIconBg: Record<NonNullable<KpiCardProps["tone"]>, string> = {
  neutral: "bg-brand-500/10 text-brand-400",
  gain: "bg-gain-500/10 text-gain-400",
  loss: "bg-loss-500/10 text-loss-400",
  gold: "bg-gold-500/10 text-gold-400",
};

export function KpiCard({
  label,
  value,
  delta,
  deltaLabel,
  icon: Icon,
  tone = "neutral",
}: KpiCardProps) {
  const positive = delta !== undefined && delta >= 0;
  return (
    <div className={clsx("glass relative overflow-hidden p-5 ring-1", toneRing[tone])}>
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            {label}
          </p>
          <p className="text-2xl font-semibold tabular text-slate-50">{value}</p>
          {(delta !== undefined || deltaLabel) && (
            <div className="flex items-center gap-1.5 pt-1 text-xs">
              {delta !== undefined && (
                <span
                  className={clsx(
                    "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 font-medium",
                    positive
                      ? "bg-gain-500/10 text-gain-400"
                      : "bg-loss-500/10 text-loss-400"
                  )}
                >
                  {positive ? (
                    <TrendingUp className="h-3 w-3" />
                  ) : (
                    <TrendingDown className="h-3 w-3" />
                  )}
                  {Math.abs(delta).toFixed(1)}%
                </span>
              )}
              {deltaLabel && <span className="text-slate-400">{deltaLabel}</span>}
            </div>
          )}
        </div>
        {Icon && (
          <div
            className={clsx(
              "flex h-10 w-10 items-center justify-center rounded-xl",
              toneIconBg[tone]
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
        )}
      </div>
    </div>
  );
}
