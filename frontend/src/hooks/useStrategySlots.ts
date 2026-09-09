import { useCallback, useEffect, useState } from "react";
import {
  createStrategySlot,
  deleteStrategySlot,
  getStrategySlots,
  toggleStrategySlot,
  updateStrategySlot,
} from "../api/strategySlots";
import type { SlotDeletionResult, StrategySlot, StrategySlotWriteInput } from "../types/strategySlots";
import { useAuth } from "./useAuth";

const POLL_INTERVAL_MS = 5000;

// 07-auto-trading 페이지가 소유하는 슬롯 목록 상태. 워커가 서버에서 상시 도는 동안 체결·
// 손절익절로 슬롯 상태(is_active, state.position)가 화면 조작 없이도 바뀔 수 있으므로
// (00-overview.md 원칙 1), useOrders와 같은 폴링 패턴을 쓴다.
// ManualTradingPage도 잠금 코인 목록을 얻으려고 이 훅을 그대로 재사용한다.
export function useStrategySlots() {
  const { token } = useAuth();
  const [slots, setSlots] = useState<StrategySlot[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!token) return;
    const list = await getStrategySlots(token);
    setSlots(list);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    setIsLoading(true);
    refresh()
      .catch(() => undefined)
      .finally(() => setIsLoading(false));
    const timer = setInterval(() => {
      refresh().catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [token, refresh]);

  const createSlot = useCallback(
    async (input: StrategySlotWriteInput) => {
      if (!token) return;
      await createStrategySlot(token, input);
      await refresh();
    },
    [token, refresh],
  );

  const updateSlot = useCallback(
    async (slotId: number, input: StrategySlotWriteInput) => {
      if (!token) return;
      await updateStrategySlot(token, slotId, input);
      await refresh();
    },
    [token, refresh],
  );

  const toggleSlot = useCallback(
    async (slotId: number, isActive: boolean) => {
      if (!token) return;
      await toggleStrategySlot(token, slotId, isActive);
      await refresh();
    },
    [token, refresh],
  );

  const deleteSlot = useCallback(
    async (slotId: number): Promise<SlotDeletionResult | undefined> => {
      if (!token) return undefined;
      const result = await deleteStrategySlot(token, slotId);
      await refresh();
      return result;
    },
    [token, refresh],
  );

  const lockedCoinSymbols = slots.filter((slot) => slot.is_active).map((slot) => slot.coin_symbol);

  return { slots, isLoading, lockedCoinSymbols, createSlot, updateSlot, toggleSlot, deleteSlot, refresh };
}
