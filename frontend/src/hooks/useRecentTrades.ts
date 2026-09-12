import { useEffect, useState } from "react";
import { getRecentTrades } from "../api/dashboard";
import type { RecentTrade } from "../types/dashboard";
import { useAuth } from "./useAuth";

export function useRecentTrades() {
  const { token } = useAuth();
  const [trades, setTrades] = useState<RecentTrade[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setIsLoading(true);
    getRecentTrades(token)
      .then((result) => {
        if (!cancelled) {
          setTrades(result);
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

  return { trades, isLoading };
}
