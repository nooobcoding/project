import { useEffect, useState } from "react";
import { getStrategySlotSignal } from "../api/strategySlots";
import type { SlotSignal } from "../types/strategySlots";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 15000; // useNotifications와 동일 주기 — 신호 조회가 캐시 미스 시
// Upbit REST를 직접 칠 수 있어(services/candles.py get_confirmed_candles) 너무 촘촘히
// 돌리지 않는다.

// 07-auto-trading.md 3-B "신호 모니터링" — 활성 슬롯에 대해서만 현재 신호를 조회한다.
// activeSlotIds는 부모(AutoTradingPage)가 useStrategySlots로 이미 가진 목록에서 뽑아 넘긴다.
export function useSlotSignals(activeSlotIds: number[]) {
  const { token } = useAuth();
  const [signals, setSignals] = useState<Record<number, SlotSignal>>({});
  const idsKey = activeSlotIds.slice().sort((a, b) => a - b).join(",");

  useEffect(() => {
    if (!token || idsKey === "") {
      setSignals({});
      return;
    }
    const ids = idsKey.split(",").map(Number);

    let cancelled = false;
    const fetchAll = async () => {
      const entries = await Promise.all(
        ids.map(async (id) => {
          try {
            return [id, await getStrategySlotSignal(token, id)] as const;
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) return;
      setSignals((prev) => {
        const next = { ...prev };
        for (const entry of entries) {
          if (entry) {
            next[entry[0]] = entry[1];
          }
        }
        return next;
      });
    };

    fetchAll().catch(() => undefined);
    const timer = setInterval(() => {
      fetchAll().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [token, idsKey]);

  return signals;
}
