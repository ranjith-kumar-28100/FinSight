import { Loader2 } from "lucide-react";

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-6 py-10 text-sm text-slate-400">
      <Loader2 className="h-4 w-4 animate-spin text-brand-400" />
      {label ?? "Loading…"}
    </div>
  );
}
