import { apiFetch } from "./client";
import type { DashboardSummary, RecentTrade, WatchlistItem } from "../types/dashboard";

export function getSummary(token: string): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/api/dashboard/summary", { token });
}

export function getWatchlist(token: string): Promise<WatchlistItem[]> {
  return apiFetch<WatchlistItem[]>("/api/watchlist", { token });
}

export function addWatchlistItem(token: string, coinSymbol: string): Promise<WatchlistItem> {
  return apiFetch<WatchlistItem>("/api/watchlist", {
    method: "POST",
    token,
    body: JSON.stringify({ coin_symbol: coinSymbol }),
  });
}

export function removeWatchlistItem(token: string, coinSymbol: string): Promise<void> {
  return apiFetch<void>(`/api/watchlist/${encodeURIComponent(coinSymbol)}`, {
    method: "DELETE",
    token,
  });
}

export function getRecentTrades(token: string): Promise<RecentTrade[]> {
  return apiFetch<RecentTrade[]>("/api/dashboard/recent-trades", { token });
}
