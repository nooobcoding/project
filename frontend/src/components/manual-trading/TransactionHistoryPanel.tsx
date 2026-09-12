import type { Order } from "../../types/orders";

interface TransactionHistoryPanelProps {
  history: Order[];
}

const STATUS_LABEL: Record<Order["status"], string> = {
  pending: "대기",
  filled: "체결",
  canceled: "취소",
};

// 체결·취소된 최근 주문 목록 — 취소 버튼 없음(과거 내역이므로 PendingOrdersList와 구분).
export function TransactionHistoryPanel({ history }: TransactionHistoryPanelProps) {
  return (
    <div className="dashboard-card trade-history-panel">
      <p className="dashboard-card-label">거래내역</p>
      {history.length === 0 ? (
        <p className="dashboard-empty-text">거래내역이 없습니다.</p>
      ) : (
        <ul className="dashboard-trade-list">
          {history.map((order) => (
            <li key={order.id} className="trade-history-item">
              <span className={order.side === "buy" ? "dashboard-trade-badge is-buy" : "dashboard-trade-badge is-sell"}>
                {order.side === "buy" ? "매수" : "매도"}
              </span>
              <span>{order.coin_symbol}</span>
              <span>{Math.round(Number(order.price)).toLocaleString("ko-KR")}</span>
              <span>{order.quantity}</span>
              <span className={order.status === "canceled" ? "trade-history-status is-canceled" : "trade-history-status"}>
                {STATUS_LABEL[order.status]}
              </span>
              <span className="trade-history-time">
                {new Date(order.filled_at ?? order.created_at).toLocaleString("ko-KR")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
