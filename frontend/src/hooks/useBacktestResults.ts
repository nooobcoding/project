import { useCallback, useEffect, useState } from "react";
import { getBacktestResults } from "../api/backtest";
import type { BacktestResultSummary } from "../types/backtest";
import { useAuth } from "./useAuth";

// 저장된 백테스트 결과 목록(불러오기 팝업용, 06-backtesting.md 3-A절). 워커처럼 서버가 값을
// 바꾸는 대상이 아니라 사용자가 "저장"했을 때만 늘어나므로 useCoins처럼 마운트 시 1회만
// 불러온다 — useStrategySlots와 달리 폴링하지 않는다.
export function useBacktestResults() {
  const { token } = useAuth();
  const [results, setResults] = useState<BacktestResultSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const list = await getBacktestResults(token);
    setResults(list);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
  }, [token, refresh]);

  return { results, isLoading, refresh };
}
