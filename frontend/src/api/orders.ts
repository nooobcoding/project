import { apiFetch } from "./client";
import type { Order, OrderCreateInput } from "../types/orders";

export function getPendingOrders(token: string): Promise<Order[]> {
  return apiFetch<Order[]>("/api/orders?status=pending", { token });
}

export function createOrder(token: string, input: OrderCreateInput): Promise<Order> {
  return apiFetch<Order>("/api/orders", {
    method: "POST",
    token,
    body: JSON.stringify(input),
  });
}

export function cancelOrder(token: string, orderId: number): Promise<void> {
  return apiFetch<void>(`/api/orders/${orderId}`, { method: "DELETE", token });
}

export function getOrderHistory(token: string, symbol?: string): Promise<Order[]> {
  const query = symbol ? `&coin_symbol=${encodeURIComponent(symbol)}` : "";
  return apiFetch<Order[]>(`/api/orders?status=history${query}`, { token });
}

// 07-auto-trading.md 3-B "자동매매 체결 내역" — source=auto만 필터링, 슬롯 단위 필터도 가능.
export function getAutoTradeHistory(token: string, strategySlotId?: number): Promise<Order[]> {
  const query = strategySlotId ? `&strategy_slot_id=${strategySlotId}` : "";
  return apiFetch<Order[]>(`/api/orders?status=history&source=auto${query}`, { token });
}
