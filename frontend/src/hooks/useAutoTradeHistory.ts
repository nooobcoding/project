import { useCallback, useEffect, useState } from "react";
import { getAutoTradeHistory } from "../api/orders";
import type { Order } from "../types/orders";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 5000;

// 07-auto-trading.md 3-B "자동매매 체결 내역" (orders 중 source=auto).
export function useAutoTradeHistory() {
  const { token } = useAuth();
  const [history, setHistory] = useState<Order[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const list = await getAutoTradeHistory(token);
    setHistory(list);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [token, refresh]);

  return { history, isLoading, refresh };
}
