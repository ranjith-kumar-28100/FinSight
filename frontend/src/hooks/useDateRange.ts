import { createContext, useContext } from "react";

export interface DateRangeCtx {
  start: string | null;
  end: string | null;
  setRange: (start: string | null, end: string | null) => void;
  minDate: string | null;
  maxDate: string | null;
}

export const DateRangeContext = createContext<DateRangeCtx | null>(null);

export function useDateRange(): DateRangeCtx {
  const ctx = useContext(DateRangeContext);
  if (!ctx) throw new Error("useDateRange must be used inside DateRangeProvider");
  return ctx;
}
