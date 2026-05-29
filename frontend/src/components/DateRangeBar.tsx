import { Calendar } from "lucide-react";
import { useDateRange } from "@/hooks/useDateRange";

export function DateRangeBar() {
  const { start, end, setRange, minDate, maxDate } = useDateRange();

  // Allow the picker to extend ±365 days past the data so users can frame
  // look-ahead comparisons or "what if I include next quarter" scenarios.
  const addDays = (iso: string, days: number) => {
    const d = new Date(iso);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  };
  const minLimit = minDate ? addDays(minDate, -365) : undefined;
  const maxLimit = maxDate ? addDays(maxDate, 365) : undefined;

  if (!minDate || !maxDate) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 text-xs text-slate-500">
        <Calendar className="h-3.5 w-3.5" />
        Upload statements to enable date filtering
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5">
      <Calendar className="h-3.5 w-3.5 text-brand-400" />
      <span className="text-xs font-medium text-slate-300">Range</span>
      <input
        type="date"
        value={start ?? minDate}
        min={minLimit}
        max={maxLimit}
        onChange={(e) => setRange(e.target.value || null, end)}
        className="rounded-md border border-line bg-ink-800/80 px-2 py-0.5 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
      <span className="text-xs text-slate-500">→</span>
      <input
        type="date"
        value={end ?? maxDate}
        min={minLimit}
        max={maxLimit}
        onChange={(e) => setRange(start, e.target.value || null)}
        className="rounded-md border border-line bg-ink-800/80 px-2 py-0.5 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
      {(start !== minDate || end !== maxDate) && (
        <button
          onClick={() => setRange(minDate, maxDate)}
          className="ml-1 text-[11px] font-medium text-brand-400 hover:text-brand-300"
        >
          Reset
        </button>
      )}
    </div>
  );
}
