import { useCallback, useEffect, useState } from "react";
import * as dashboardApi from "../api/dashboard";
import type { WatchlistItem } from "../types/dashboard";
import { useAuth } from "./useAuth";

const SELECTED_COIN_STORAGE_KEY = "coin_autotrading_selected_coin";

export function useWatchlist() {
  const { token } = useAuth();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedSymbol, setSelectedSymbolState] = useState<string | null>(() =>
    localStorage.getItem(SELECTED_COIN_STORAGE_KEY),
  );

  const refresh = useCallback(async () => {
    if (!token) return [];
    const list = await dashboardApi.getWatchlist(token);
    setItems(list);
    return list;
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token, refresh]);

  const selectSymbol = useCallback((symbol: string) => {
    setSelectedSymbolState(symbol);
    localStorage.setItem(SELECTED_COIN_STORAGE_KEY, symbol);
  }, []);

  useEffect(() => {
    // 선택된 탭이 없거나(최초 방문) 제거되어 목록에 없으면 첫 항목으로 보정한다
    // (02-dashboard.md 2-B — 마지막 선택 탭은 localStorage에 저장, 스키마 변경 없이 복원).
    if (items.length === 0) {
      return;
    }
    if (!selectedSymbol || !items.some((item) => item.coin_symbol === selectedSymbol)) {
      selectSymbol(items[0].coin_symbol);
    }
  }, [items, selectedSymbol, selectSymbol]);

  const addItem = useCallback(
    async (symbol: string) => {
      if (!token) return;
      const created = await dashboardApi.addWatchlistItem(token, symbol);
      await refresh();
      selectSymbol(created.coin_symbol);
    },
    [token, refresh, selectSymbol],
  );

  const removeItem = useCallback(
    async (symbol: string) => {
      if (!token) return;
      await dashboardApi.removeWatchlistItem(token, symbol);
      await refresh();
    },
    [token, refresh],
  );

  return {
    items,
    isLoading,
    selectedSymbol: items.length === 0 ? null : selectedSymbol,
    selectSymbol,
    addItem,
    removeItem,
  };
}
