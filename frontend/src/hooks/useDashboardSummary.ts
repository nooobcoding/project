import { useEffect, useState } from "react";
import { getSummary } from "../api/dashboard";
import type { DashboardSummary } from "../types/dashboard";
import { useAuth } from "./useAuth";

export function useDashboardSummary() {
  const { token } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setIsLoading(true);
    getSummary(token)
      .then((result) => {
        if (!cancelled) {
          setSummary(result);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return { summary, isLoading };
}
