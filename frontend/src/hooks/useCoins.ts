import { useEffect, useState } from "react";
import { getCoins } from "../api/coins";
import type { Coin } from "../types/coins";
import { useAuth } from "./useAuth";

// 03-manual-trading 1열 코인 목록 — GET /api/coins를 1회 조회한다. 시세 자체는
// usePriceStream 구독이 갱신하므로(코인 목록은 실시간으로 늘거나 줄지 않는다) 여기서는
// 정적 목록(심볼/이름)만 다룬다.
export function useCoins() {
  const { token } = useAuth();
  const [coins, setCoins] = useState<Coin[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setIsLoading(true);
    getCoins(token)
      .then((result) => {
        if (!cancelled) {
          setCoins(result);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return { coins, isLoading };
}
