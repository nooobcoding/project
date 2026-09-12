import { apiFetch } from "./client";
import type {
  SlotDeletionResult,
  SlotSignal,
  StrategySlot,
  StrategySlotWriteInput,
} from "../types/strategySlots";

export function getStrategySlots(token: string): Promise<StrategySlot[]> {
  return apiFetch<StrategySlot[]>("/api/strategy-slots", { token });
}

export function createStrategySlot(
  token: string,
  input: StrategySlotWriteInput,
): Promise<StrategySlot> {
  return apiFetch<StrategySlot>("/api/strategy-slots", {
    method: "POST",
    token,
    body: JSON.stringify(input),
  });
}

// PATCH 공용 엔드포인트 — is_active만 보내면 ON/OFF 토글, 그 외 필드를 보내면 설정 수정이다
// (backend/app/schemas/strategy_slots.py StrategySlotPatchRequest). 두 종류를 섞지 않는다.
export function updateStrategySlot(
  token: string,
  slotId: number,
  input: StrategySlotWriteInput,
): Promise<StrategySlot> {
  return apiFetch<StrategySlot>(`/api/strategy-slots/${slotId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(input),
  });
}

export function toggleStrategySlot(
  token: string,
  slotId: number,
  isActive: boolean,
): Promise<StrategySlot> {
  return apiFetch<StrategySlot>(`/api/strategy-slots/${slotId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify({ is_active: isActive }),
  });
}

export function deleteStrategySlot(token: string, slotId: number): Promise<SlotDeletionResult> {
  return apiFetch<SlotDeletionResult>(`/api/strategy-slots/${slotId}`, {
    method: "DELETE",
    token,
  });
}

export function getStrategySlotSignal(token: string, slotId: number): Promise<SlotSignal> {
  return apiFetch<SlotSignal>(`/api/strategy-slots/${slotId}/signals`, { token });
}
