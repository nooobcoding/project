import { useState } from "react";
import { ApiError } from "../../api/client";
import type { BacktestResultSummary } from "../../types/backtest";
import { INDICATOR_LABEL, STRATEGY_TYPE_LABEL } from "./backtestConstants";

interface BacktestLoadModalProps {
  results: BacktestResultSummary[];
  isLoading: boolean;
  onSelect: (id: number) => void;
  onDelete: (id: number) => Promise<void>;
  onClose: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", { dateStyle: "medium" });
}

// 06-backtesting.md 3-A절 "결과 불러오기 — 라벨+저장일+요약수익률 목록 팝업".
export function BacktestLoadModal({ results, isLoading, onSelect, onDelete, onClose }: BacktestLoadModalProps) {
  // 삭제는 되돌릴 수 없어(components/auto-trading/DeleteSlotModal.tsx와 같은 이유) 곧바로
  // 지우지 않고, 행 하나를 확인 문구로 바꿔치기하는 가벼운 인라인 확인을 한 단계 더 둔다.
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | undefined>();

  const handleDelete = async (id: number) => {
    setIsDeleting(true);
    setDeleteError(undefined);
    try {
      await onDelete(id);
      setPendingDeleteId(null);
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "삭제 처리에 실패했습니다.");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal backtest-load-modal" onClick={(event) => event.stopPropagation()}>
        <h3>저장된 결과 불러오기</h3>

        {isLoading && <p className="dashboard-empty-text">불러오는 중...</p>}
        {!isLoading && results.length === 0 && (
          <p className="dashboard-empty-text">저장된 백테스트 결과가 없습니다.</p>
        )}

        {results.length > 0 && (
          <ul className="backtest-result-list">
            {results.map((result) => {
              const totalReturn = Number(result.total_return);
              const isPendingDelete = pendingDeleteId === result.id;

              return (
                <li
                  key={result.id}
                  className="backtest-result-list-item"
                  onClick={isPendingDelete ? undefined : () => onSelect(result.id)}
                >
                  {isPendingDelete ? (
                    <div className="backtest-result-delete-confirm" onClick={(event) => event.stopPropagation()}>
                      <span>&quot;{result.label}&quot; 결과를 삭제하시겠습니까?</span>
                      <div className="backtest-result-delete-actions">
                        <button
                          type="button"
                          className="dashboard-chip-button"
                          onClick={() => setPendingDeleteId(null)}
                          disabled={isDeleting}
                        >
                          취소
                        </button>
                        <button
                          type="button"
                          className="settings-danger-button"
                          onClick={() => handleDelete(result.id)}
                          disabled={isDeleting}
                        >
                          {isDeleting ? "삭제 중..." : "삭제"}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="backtest-result-list-main">
                        <span className="backtest-result-list-label">{result.label}</span>
                        <span className="dashboard-card-label">
                          {STRATEGY_TYPE_LABEL[result.strategy_type]}
                          {result.indicator ? ` · ${INDICATOR_LABEL[result.indicator]}` : ""} ·{" "}
                          {result.coin_symbol}
                        </span>
                      </div>
                      <div className="backtest-result-list-meta">
                        <span className={totalReturn >= 0 ? "is-positive" : "is-negative"}>
                          {totalReturn >= 0 ? "+" : ""}
                          {totalReturn.toFixed(2)}%
                        </span>
                        <span className="dashboard-card-label">{formatDate(result.created_at)}</span>
                      </div>
                      <button
                        type="button"
                        className="dashboard-remove-button"
                        aria-label="결과 삭제"
                        onClick={(event) => {
                          event.stopPropagation();
                          setDeleteError(undefined);
                          setPendingDeleteId(result.id);
                        }}
                      >
                        ×
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {deleteError && <p className="auth-error-message">{deleteError}</p>}

        <div className="dashboard-modal-actions">
          <button type="button" className="dashboard-chip-button" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
