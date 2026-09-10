import { useState } from "react";
import { ApiError } from "../../api/client";
import { ToggleSwitch } from "../ToggleSwitch";
import type { Coin } from "../../types/coins";
import type {
  SlotDeletionResult,
  StrategySlot,
  StrategySlotWriteInput,
} from "../../types/strategySlots";
import { DeleteSlotModal } from "./DeleteSlotModal";
import { SlotFormModal } from "./SlotFormModal";

interface SlotListPanelProps {
  slots: StrategySlot[];
  coins: Coin[];
  onCreate: (input: StrategySlotWriteInput) => Promise<void>;
  onUpdate: (slotId: number, input: StrategySlotWriteInput) => Promise<void>;
  onToggle: (slotId: number, isActive: boolean) => Promise<void>;
  onDelete: (slotId: number) => Promise<SlotDeletionResult | undefined>;
  onError: (message: string) => void;
}

const STRATEGY_TYPE_LABEL: Record<string, string> = {
  trend: "추세추종",
  counter_trend: "역추세",
  grid: "그리드",
};

// 그리드는 지표를 쓰지 않아 indicator가 null이다 — 배지 자체를 그리지 않는다.
const INDICATOR_LABEL: Record<string, string> = {
  ma: "MA",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "볼린저",
};

function koreanNameFor(coins: Coin[], symbol: string): string {
  return coins.find((coin) => coin.symbol === symbol)?.korean_name ?? symbol;
}

// 07-auto-trading.md 3-A — 1열 전략 슬롯 목록. "+ 전략 추가"·카드 클릭(수정)·ON/OFF 토글·
// 삭제를 모두 이 패널이 트리거하되, 실제 데이터 변경은 부모(AutoTradingPage)가 넘긴 콜백으로
// 위임한다(useStrategySlots 훅은 페이지만 소유). 모달 열림 여부는 상호작용 상태일 뿐이라
// settings/AccountSettingsPanel의 DeleteAccountModal과 같은 방식으로 이 패널이 직접 갖는다.
export function SlotListPanel({
  slots,
  coins,
  onCreate,
  onUpdate,
  onToggle,
  onDelete,
  onError,
}: SlotListPanelProps) {
  const [formSlot, setFormSlot] = useState<StrategySlot | null | undefined>(undefined); // undefined=닫힘, null=생성, 값=수정
  const [deleteTarget, setDeleteTarget] = useState<StrategySlot | null>(null);
  const [pendingToggleId, setPendingToggleId] = useState<number | null>(null);

  const handleToggle = async (slot: StrategySlot, isActive: boolean) => {
    setPendingToggleId(slot.id);
    try {
      await onToggle(slot.id, isActive);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setPendingToggleId(null);
    }
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    await onDelete(deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <div className="trade-panel auto-slot-list-panel">
      <div className="dashboard-card-header">
        <p className="dashboard-card-label">전략 슬롯</p>
        <button type="button" className="dashboard-chip-button" onClick={() => setFormSlot(null)}>
          + 전략 추가
        </button>
      </div>

      {slots.length === 0 ? (
        <p className="dashboard-empty-text">등록된 전략이 없습니다.</p>
      ) : (
        <ul className="auto-slot-list">
          {slots.map((slot) => (
            <li key={slot.id} className="auto-slot-card">
              <div className="auto-slot-card-main" onClick={() => setFormSlot(slot)}>
                <div className="auto-slot-card-title">
                  <span>{koreanNameFor(coins, slot.coin_symbol)}</span>
                  <span className="auto-slot-card-symbol">{slot.coin_symbol}</span>
                </div>
                <div className="auto-slot-card-badges">
                  <span className="auto-slot-badge">{STRATEGY_TYPE_LABEL[slot.strategy_type]}</span>
                  {slot.indicator && (
                    <span className="auto-slot-badge">{INDICATOR_LABEL[slot.indicator]}</span>
                  )}
                </div>
              </div>
              <div className="auto-slot-card-actions">
                <ToggleSwitch
                  checked={slot.is_active}
                  disabled={pendingToggleId === slot.id}
                  onChange={(value) => handleToggle(slot, value)}
                  label={`${slot.coin_symbol} 전략 ${slot.is_active ? "끄기" : "켜기"}`}
                />
                <button
                  type="button"
                  className="dashboard-remove-button"
                  onClick={() => setDeleteTarget(slot)}
                  aria-label={`${slot.coin_symbol} 전략 삭제`}
                >
                  삭제
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {formSlot !== undefined && (
        <SlotFormModal
          coins={coins}
          slot={formSlot}
          onClose={() => setFormSlot(undefined)}
          onCreate={onCreate}
          onUpdate={onUpdate}
        />
      )}

      {deleteTarget && (
        <DeleteSlotModal
          slot={deleteTarget}
          koreanName={koreanNameFor(coins, deleteTarget.coin_symbol)}
          onClose={() => setDeleteTarget(null)}
          onConfirm={handleDeleteConfirm}
        />
      )}
    </div>
  );
}
