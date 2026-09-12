import type { RecentTrade } from "../../types/dashboard";

interface RecentTradesListProps {
  trades: RecentTrade[];
  isLoading: boolean;
}

export function RecentTradesList({ trades, isLoading }: RecentTradesListProps) {
  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">최근 거래 내역</p>
      {isLoading ? (
        <p className="dashboard-empty-text">불러오는 중...</p>
      ) : trades.length === 0 ? (
        // 03-manual-trading 완료 전까지 항상 빈 목록이다 (02-dashboard.md 2-C).
        <p className="dashboard-empty-text">최근 체결 내역이 없습니다.</p>
      ) : (
        <ul className="dashboard-trade-list">
          {trades.map((trade, index) => (
            <li key={index} className="dashboard-trade-list-item">
              <span className={trade.side === "buy" ? "dashboard-trade-badge is-buy" : "dashboard-trade-badge is-sell"}>
                {trade.side === "buy" ? "매수" : "매도"}
              </span>
              <span>{trade.coin_symbol}</span>
              <span>{Number(trade.price).toLocaleString("ko-KR")}</span>
              <span>{trade.quantity}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
