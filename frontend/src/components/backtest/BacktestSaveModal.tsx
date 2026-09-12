import { useState } from "react";
import { ApiError } from "../../api/client";
import type { BacktestRunResult } from "../../types/backtest";
import type { Coin } from "../../types/coins";
import { INDICATOR_LABEL, STRATEGY_TYPE_LABEL } from "./backtestConstants";

interface BacktestSaveModalProps {
  result: BacktestRunResult;
  coins: Coin[];
  onSave: (label: string) => Promise<void>;
  onClose: () => void;
}

// 06-backtesting.md 3-A절 "기본 라벨 자동 생성, 수정 가능" — 라벨 템플릿 조합은 화면(프론트)
// 책임이다. 백엔드는 받은 라벨을 그대로 저장할 뿐 이 문자열을 만들지 않는다
// (backend/app/schemas/backtest.py BacktestSaveRequest 참고).
function buildDefaultLabel(result: BacktestRunResult, coins: Coin[]): string {
  const coinName = coins.find((coin) => coin.symbol === result.coin_symbol)?.korean_name ?? result.coin_symbol;
  const strategyLabel = STRATEGY_TYPE_LABEL[result.strategy_type];
  const indicatorLabel = result.indicator ? INDICATOR_LABEL[result.indicator] : strategyLabel;
  const today = new Date().toISOString().slice(0, 10);
  return `${strategyLabel}-${indicatorLabel}-${coinName}-${today}`;
}

export function BacktestSaveModal({ result, coins, onSave, onClose }: BacktestSaveModalProps) {
  const [label, setLabel] = useState(() => buildDefaultLabel(result, coins));
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSave = async () => {
    if (!label.trim()) return;
    setIsSubmitting(true);
    setError(undefined);
    try {
      await onSave(label.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "저장 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal" onClick={(event) => event.stopPropagation()}>
        <h3>결과 저장</h3>
        <div className="settings-field">
          <label className="settings-field-label">라벨</label>
          <input
            className="auth-input"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            maxLength={100}
          />
        </div>
        {error && <p className="auth-error-message">{error}</p>}
        <div className="dashboard-modal-actions">
          <button type="button" className="dashboard-chip-button" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="auth-button"
            onClick={handleSave}
            disabled={isSubmitting || !label.trim()}
          >
            {isSubmitting ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
