import type { BacktestTradeOut } from "../../types/backtest";

interface BacktestTradeModalProps {
  trades: BacktestTradeOut[];
  onClose: () => void;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

// price는 NUMERIC(20,8), profit은 NUMERIC(20,4) — 원화 표시는 정수로 반올림해 보여준다.
function won(value: number): string {
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
}

// 06-backtesting.md 3-B절 "마커 클릭 시 체결상세 팝업". 그리드는 한 캔들에서 여러 라인이 동시
// 체결될 수 있어(strategy_engine/grid.py) 목록 형태로 보여준다.
export function BacktestTradeModal({ trades, onClose }: BacktestTradeModalProps) {
  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal" onClick={(event) => event.stopPropagation()}>
        <h3>체결 상세</h3>
        <ul className="dashboard-trade-list">
          {trades.map((trade, index) => (
            <li key={index} className="dashboard-trade-list-item">
              <span className={trade.side === "buy" ? "dashboard-trade-badge is-buy" : "dashboard-trade-badge is-sell"}>
                {trade.side === "buy" ? "매수" : "매도"}
              </span>
              <span>{won(Number(trade.price))}</span>
              <span>{trade.quantity}개</span>
              <span>
                {trade.profit === null
                  ? "-"
                  : `${Number(trade.profit) >= 0 ? "+" : ""}${won(Number(trade.profit))}`}
              </span>
            </li>
          ))}
        </ul>
        <p className="dashboard-card-label">{formatDateTime(trades[0].executed_at)}</p>
        <div className="dashboard-modal-actions">
          <button type="button" className="auth-button" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
