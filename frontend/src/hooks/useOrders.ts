import { useCallback, useEffect, useState } from "react";
import { cancelOrder as cancelOrderApi, createOrder, getPendingOrders } from "../api/orders";
import type { Order, OrderCreateInput } from "../types/orders";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 3000;

// 03-manual-trading 2열 미체결 목록 — 지정가 체결은 사용자 액션 없이 서버(체결 엔진)에서
// 일어날 수 있으므로, 제출/취소 직후 갱신 외에도 짧은 폴링으로 최신 상태를 반영한다.
export function useOrders() {
  const { token } = useAuth();
  const [orders, setOrders] = useState<Order[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const list = await getPendingOrders(token);
    setOrders(list);
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

  const submitOrder = useCallback(
    async (input: OrderCreateInput) => {
      if (!token) return;
      await createOrder(token, input);
      await refresh();
    },
    [token, refresh],
  );

  const cancelOrder = useCallback(
    async (orderId: number) => {
      if (!token) return;
      await cancelOrderApi(token, orderId);
      await refresh();
    },
    [token, refresh],
  );

  return { orders, isLoading, submitOrder, cancelOrder, refresh };
}
