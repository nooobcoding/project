import { useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";

interface AddCoinModalProps {
  onClose: () => void;
  onSubmit: (symbol: string) => Promise<void>;
}

export function AddCoinModal({ onClose, onSubmit }: AddCoinModalProps) {
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!symbol.trim()) {
      return;
    }
    setIsSubmitting(true);
    setError(undefined);
    try {
      await onSubmit(symbol.trim().toUpperCase());
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "관심 코인 추가에 실패했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <form
        className="dashboard-modal"
        onClick={(event) => event.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <h3>관심 코인 추가</h3>
        <input
          className="auth-input"
          placeholder="예: BTC"
          value={symbol}
          onChange={(event) => setSymbol(event.target.value)}
          autoFocus
        />
        {error && <p className="auth-error-message">{error}</p>}
        <div className="dashboard-modal-actions">
          <button type="button" className="dashboard-chip-button" onClick={onClose}>
            취소
          </button>
          <button type="submit" className="auth-button" disabled={isSubmitting}>
            추가
          </button>
        </div>
      </form>
    </div>
  );
}
