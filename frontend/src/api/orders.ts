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
