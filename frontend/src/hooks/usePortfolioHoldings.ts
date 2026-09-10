import { useCallback, useEffect, useState } from "react";
import { getPortfolioHoldings } from "../api/portfolio";
import type { HoldingItem } from "../types/portfolio";
import { useAuth } from "./useAuth";

export function usePortfolioHoldings() {
  const { token } = useAuth();
  const [items, setItems] = useState<HoldingItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const result = await getPortfolioHoldings(token);
    setItems(result);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token, refresh]);

  return { items, isLoading, refresh };
}
