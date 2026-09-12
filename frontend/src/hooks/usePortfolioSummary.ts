import { useCallback, useEffect, useState } from "react";
import { getPortfolioSummary } from "../api/portfolio";
import type { PortfolioSummary } from "../types/portfolio";
import { useAuth } from "./useAuth";

export function usePortfolioSummary() {
  const { token } = useAuth();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const result = await getPortfolioSummary(token);
    setSummary(result);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token, refresh]);

  return { summary, isLoading, refresh };
}
