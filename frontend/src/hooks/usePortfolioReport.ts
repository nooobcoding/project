import { useEffect, useState } from "react";
import { getPortfolioReport } from "../api/portfolio";
import type { PortfolioReport, ReportPeriod } from "../types/portfolio";
import { useAuth } from "./useAuth";

export function usePortfolioReport(period: ReportPeriod) {
  const { token } = useAuth();
  const [report, setReport] = useState<PortfolioReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setIsLoading(true);
    getPortfolioReport(token, period)
      .then((result) => {
        if (!cancelled) setReport(result);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, period]);

  return { report, isLoading };
}
