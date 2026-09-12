import { useState } from "react";
import { ApiError } from "../../api/client";
import type { StrategySlot } from "../../types/strategySlots";

interface DeleteSlotModalProps {
  slot: StrategySlot;
  koreanName: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

// 07-auto-trading.md 4.2절 — "이 전략이 보유한 [코인] N개는 수동 보유분으로 남습니다" 안내.
// 삭제 API 자체는 삭제를 실행하면서 잔여 수량을 응답으로 돌려주는 구조라(사전 조회 API가
// 따로 없음), 확인 모달에서 미리 보여줄 수량은 이미 목록 조회로 가진 slot.state.position에서
// 읽는다 — 모달을 띄운 시점과 실제 삭제 시점 사이에 워커가 그 사이 체결을 냈다면 약간 다를 수
// 있지만(낮은 확률의 정상 오차), 사전 경고 문구의 목적(수동 보유분으로 남는다는 사실 인지)에는
// 지장이 없다.
export function DeleteSlotModal({ slot, koreanName, onClose, onConfirm }: DeleteSlotModalProps) {
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const remainingQuantity = slot.state.position?.quantity;

  const handleConfirm = async () => {
    setIsSubmitting(true);
    setError(undefined);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "삭제 처리에 실패했습니다.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal" onClick={(event) => event.stopPropagation()}>
        <h3>전략 삭제</h3>
        <p className="settings-caption">
          {remainingQuantity
            ? `이 전략이 보유한 ${koreanName} ${remainingQuantity}개는 수동 보유분으로 남습니다.`
            : `${koreanName} 전략을 삭제하시겠습니까?`}
        </p>
        {error && <p className="auth-error-message">{error}</p>}
        <div className="dashboard-modal-actions">
          <button type="button" className="dashboard-chip-button" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="settings-danger-button"
            onClick={handleConfirm}
            disabled={isSubmitting}
          >
            {isSubmitting ? "삭제 처리 중..." : "삭제하기"}
          </button>
        </div>
      </div>
    </div>
  );
}
