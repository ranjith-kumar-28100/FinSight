import { NavLink, Outlet } from "react-router-dom";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  CalendarRange,
  LayoutDashboard,
  ListChecks,
  Receipt,
  Repeat,
  Target,
  TrendingUp,
  UploadCloud,
  Wallet,
} from "lucide-react";
import clsx from "clsx";

import { DateRangeBar } from "./DateRangeBar";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/transactions", label: "Transactions", icon: Receipt },
  { to: "/insights", label: "Insights", icon: BarChart3 },
  { to: "/monthly-map", label: "Monthly Map", icon: CalendarRange },
  { to: "/recurring", label: "Recurring", icon: Repeat },
  { to: "/forecast", label: "Forecast", icon: TrendingUp },
  { to: "/goals", label: "Goals", icon: Target },
  { to: "/anomalies", label: "Anomalies", icon: AlertTriangle },
  { to: "/chat", label: "Chat", icon: Bot },
  { to: "/upload", label: "Upload", icon: UploadCloud },
];

export function Layout() {
  return (
    <div className="relative isolate min-h-screen bg-ink-950 bg-grid-fade">
      <div className="grid min-h-screen grid-cols-[260px_1fr]">
        {/* Sidebar */}
        <aside className="border-r border-line bg-ink-900/60 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-2 px-5 border-b border-line">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-gain-500 shadow-md shadow-brand-700/30">
              <Wallet className="h-4 w-4 text-white" />
            </div>
            <div>
              <div className="text-sm font-bold tracking-tight text-slate-100">
                FinSight
              </div>
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                Personal Finance
              </div>
            </div>
          </div>
          <nav className="space-y-0.5 px-3 py-4">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition",
                    isActive
                      ? "bg-gradient-to-r from-brand-600/30 to-brand-500/10 text-slate-100 ring-1 ring-brand-500/30"
                      : "text-slate-400 hover:bg-surface-strong hover:text-slate-200"
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>

        </aside>

        {/* Main */}
        <main className="flex min-w-0 flex-col">
          <header className="sticky top-0 z-10 flex h-16 items-center justify-end gap-3 border-b border-line bg-ink-950/70 px-6 backdrop-blur-xl">
            <DateRangeBar />
            <a
              href="http://127.0.0.1:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="chip"
              title="OpenAPI docs"
            >
              <ListChecks className="h-3 w-3" />
              API
            </a>
          </header>
          <div className="flex-1 overflow-y-auto px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
