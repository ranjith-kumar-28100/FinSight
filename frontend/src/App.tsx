import { useEffect, useMemo, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Layout } from "@/components/Layout";
import { DateRangeContext } from "@/hooks/useDateRange";
import { getHealth } from "@/api/endpoints";

import { DashboardPage } from "@/pages/DashboardPage";
import { TransactionsPage } from "@/pages/TransactionsPage";
import { InsightsPage } from "@/pages/InsightsPage";
import { MonthlyMapPage } from "@/pages/MonthlyMapPage";
import { RecurringPage } from "@/pages/RecurringPage";
import { ForecastPage } from "@/pages/ForecastPage";
import { GoalsPage } from "@/pages/GoalsPage";
import { AnomaliesPage } from "@/pages/AnomaliesPage";
import { ChatPage } from "@/pages/ChatPage";
import { UploadPage } from "@/pages/UploadPage";

export default function App() {
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
    refetchInterval: 30_000,
  });

  const minDate = health?.data_min_date ?? null;
  const maxDate = health?.data_max_date ?? null;

  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);

  // Seed the picker once the backend reports a data range.
  useEffect(() => {
    if (minDate && start === null) setStart(minDate);
    if (maxDate && end === null) setEnd(maxDate);
  }, [minDate, maxDate, start, end]);

  const ctx = useMemo(
    () => ({
      start,
      end,
      setRange: (s: string | null, e: string | null) => {
        setStart(s);
        setEnd(e);
      },
      minDate,
      maxDate,
    }),
    [start, end, minDate, maxDate]
  );

  return (
    <DateRangeContext.Provider value={ctx}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="/transactions" element={<TransactionsPage />} />
          <Route path="/insights" element={<InsightsPage />} />
          <Route path="/monthly-map" element={<MonthlyMapPage />} />
          <Route path="/recurring" element={<RecurringPage />} />
          <Route path="/forecast" element={<ForecastPage />} />
          <Route path="/goals" element={<GoalsPage />} />
          <Route path="/anomalies" element={<AnomaliesPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/upload" element={<UploadPage />} />
        </Route>
      </Routes>
    </DateRangeContext.Provider>
  );
}
