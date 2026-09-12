import type { Order } from "../../types/orders";

interface PendingOrdersListProps {
  orders: Order[];
  onCancel: (orderId: number) => void;
}

// 03-manual-trading.md 2-B — 미체결 주문 목록, 취소는 확인 없이 즉시 처리한다.
export function PendingOrdersList({ orders, onCancel }: PendingOrdersListProps) {
  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">미체결 주문</p>
      {orders.length === 0 ? (
        <p className="dashboard-empty-text">미체결 주문이 없습니다.</p>
      ) : (
        <ul className="dashboard-trade-list">
          {orders.map((order) => (
            <li key={order.id} className="trade-pending-order-item">
              <span className={order.side === "buy" ? "dashboard-trade-badge is-buy" : "dashboard-trade-badge is-sell"}>
                {order.side === "buy" ? "매수" : "매도"}
              </span>
              <span>{order.coin_symbol}</span>
              <span>
                {order.order_type === "reserved"
                  ? `예약 ${Math.round(Number(order.trigger_price)).toLocaleString("ko-KR")} → ${Math.round(Number(order.price)).toLocaleString("ko-KR")}`
                  : Math.round(Number(order.price)).toLocaleString("ko-KR")}
              </span>
              <span>{order.quantity}</span>
              <button
                className="dashboard-remove-button"
                onClick={() => onCancel(order.id)}
                aria-label={`주문 ${order.id} 취소`}
              >
                취소
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
