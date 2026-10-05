import { useState, type ReactNode } from "react";
import { ApiError } from "../../api/client";

interface ConfirmModalProps {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

// 되돌리기 어려운 관리자 행위의 확인 모달 (DeleteAccountModal과 같은 dashboard-modal-* 클래스).
// 실패하면 닫지 않고 서버 문구를 그대로 보여준다 — "본인 계정은 정지할 수 없습니다." 등.
export function ConfirmModal({ title, children, confirmLabel, danger, onClose, onConfirm }: ConfirmModalProps) {
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    setIsSubmitting(true);
    setError(undefined);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "처리에 실패했습니다.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal" onClick={(event) => event.stopPropagation()}>
        <h3>{title}</h3>
        <div className="settings-caption">{children}</div>
        {error && <p className="auth-error-message">{error}</p>}
        <div className="dashboard-modal-actions">
          <button type="button" className="dashboard-chip-button" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className={danger ? "settings-danger-button" : "admin-primary-button"}
            onClick={handleConfirm}
            disabled={isSubmitting}
          >
            {isSubmitting ? "처리 중..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
