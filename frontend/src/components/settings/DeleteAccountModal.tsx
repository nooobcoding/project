import { useState } from "react";
import { ApiError } from "../../api/client";

interface DeleteAccountModalProps {
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

// 04-settings.md 2-A — 회원 탈퇴 확인 모달 (dashboard-modal-* 클래스를 AddCoinModal과 공유)
export function DeleteAccountModal({ onClose, onConfirm }: DeleteAccountModalProps) {
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    setIsSubmitting(true);
    setError(undefined);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "탈퇴 처리에 실패했습니다.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal" onClick={(event) => event.stopPropagation()}>
        <h3>회원 탈퇴</h3>
        <p className="settings-caption">
          탈퇴 시 모든 자산·거래 내역이 삭제되며 복구할 수 없습니다.
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
            {isSubmitting ? "탈퇴 처리 중..." : "탈퇴하기"}
          </button>
        </div>
      </div>
    </div>
  );
}
