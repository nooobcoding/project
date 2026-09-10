import { useCallback, useEffect, useState } from "react";
import { getPortfolioTrades } from "../api/portfolio";
import type { CoinRef, TradeItem, TradeSide, TradeSource } from "../types/portfolio";
import { useAuth } from "./useAuth";

const PAGE_SIZE = 20; // 08-portfolio.md 2-B

interface UsePortfolioTradesOptions {
  side: TradeSide | null;
  source: TradeSource | null;
  coinSymbol: string | null;
  page: number;
}

export function usePortfolioTrades({ side, source, coinSymbol, page }: UsePortfolioTradesOptions) {
  const { token } = useAuth();
  const [items, setItems] = useState<TradeItem[]>([]);
  const [total, setTotal] = useState(0);
  const [tradedCoins, setTradedCoins] = useState<CoinRef[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const result = await getPortfolioTrades(token, { side, source, coinSymbol }, page, PAGE_SIZE);
    setItems(result.items);
    setTotal(result.total);
    setTradedCoins(result.traded_coins);
  }, [token, side, source, coinSymbol, page]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token, refresh]);

  return { items, total, tradedCoins, pageSize: PAGE_SIZE, isLoading };
}
