import { useCallback, useEffect, useState } from "react";
import { getWalletBalance } from "../api/wallet";
import type { WalletBalance } from "../types/wallet";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 3000;

// 05-deposit-withdraw 잔고 카드·출금 검증 미리보기용. 매수/매도 체결이 사용자 액션 없이도
// 서버(체결 엔진)에서 일어나 krw_balance가 바뀔 수 있으므로 useAvailableBalance와 동일한
// 이유로 짧게 폴링한다.
export function useWalletBalance() {
  const { token } = useAuth();
  const [balance, setBalance] = useState<WalletBalance | null>(null);

  const refresh = useCallback(async () => {
    if (!token) return;
    const result = await getWalletBalance(token);
    setBalance(result);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    refresh().catch(() => undefined);
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [token, refresh]);

  return { balance, refresh };
}
