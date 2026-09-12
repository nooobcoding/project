import type { BacktestResultSummary } from "../../types/backtest";
import { INDICATOR_LABEL, STRATEGY_TYPE_LABEL } from "./backtestConstants";

interface BacktestLoadModalProps {
  results: BacktestResultSummary[];
  isLoading: boolean;
  onSelect: (id: number) => void;
  onClose: () => void;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ko-KR", { dateStyle: "medium" });
}

// 06-backtesting.md 3-A절 "결과 불러오기 — 라벨+저장일+요약수익률 목록 팝업".
export function BacktestLoadModal({ results, isLoading, onSelect, onClose }: BacktestLoadModalProps) {
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
              return (
                <li
                  key={result.id}
                  className="backtest-result-list-item"
                  onClick={() => onSelect(result.id)}
                >
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
                </li>
              );
            })}
          </ul>
        )}

        <div className="dashboard-modal-actions">
          <button type="button" className="dashboard-chip-button" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
