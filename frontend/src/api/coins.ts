import { apiFetch } from "./client";
import type { AvailableBalance, Coin } from "../types/coins";

export function getCoins(token: string): Promise<Coin[]> {
  return apiFetch<Coin[]>("/api/coins", { token });
}

export function getAvailableBalance(token: string, symbol: string): Promise<AvailableBalance> {
  return apiFetch<AvailableBalance>(`/api/coins/${encodeURIComponent(symbol)}/balance`, { token });
}
