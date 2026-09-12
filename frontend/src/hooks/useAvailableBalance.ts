import { useCallback, useEffect, useState } from "react";
import { getAvailableBalance } from "../api/coins";
import type { AvailableBalance } from "../types/coins";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 3000;

// 03-manual-trading 4열 가용 잔고 표시·비율버튼 계산용. 지정가 체결이 사용자 액션 없이
// 서버에서 일어날 수 있으므로 useOrders와 동일한 이유로 짧게 폴링한다.
export function useAvailableBalance(symbol: string | null) {
  const { token } = useAuth();
  const [balance, setBalance] = useState<AvailableBalance | null>(null);

  const refresh = useCallback(async () => {
    if (!token || !symbol) return;
    const result = await getAvailableBalance(token, symbol);
    setBalance(result);
  }, [token, symbol]);

  useEffect(() => {
    setBalance(null);
    if (!token || !symbol) return;
    refresh().catch(() => undefined);
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [token, symbol, refresh]);

  return { balance, refresh };
}
