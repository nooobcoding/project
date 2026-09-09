import { useCallback, useEffect, useState } from "react";
import { getOrderHistory } from "../api/orders";
import type { Order } from "../types/orders";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 3000;

// 03-manual-trading 거래내역 — 체결·취소는 사용자 액션 없이도(체결 엔진) 일어날 수 있으므로
// useOrders와 동일한 이유로 짧게 폴링한다. 조회 전용(제출/취소 없음).
export function useOrderHistory(symbol: string | null) {
  const { token } = useAuth();
  const [history, setHistory] = useState<Order[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token || !symbol) return;
    const list = await getOrderHistory(token, symbol);
    setHistory(list);
  }, [token, symbol]);

  useEffect(() => {
    if (!token || !symbol) {
      setHistory([]);
      return;
    }
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [token, symbol, refresh]);

  return { history, isLoading };
}
