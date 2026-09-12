import { useMemo, useState } from "react";
import type { Coin } from "../../types/coins";
import type { Order } from "../../types/orders";
import type { StrategySlot } from "../../types/strategySlots";

interface AutoTradeHistoryPanelProps {
  history: Order[];
  slots: StrategySlot[];
  coins: Coin[];
}

const STATUS_LABEL: Record<Order["status"], string> = {
  pending: "대기",
  filled: "체결",
  canceled: "취소",
};

// 07-auto-trading.md 3-B "자동매매 체결 내역 — orders 중 source=auto만 필터링, 슬롯별 필터
// 가능". 목록 자체(useAutoTradeHistory)는 이미 source=auto로 가져오므로, 여기서는 슬롯 단위
// 필터만 클라이언트에서 처리한다.
export function AutoTradeHistoryPanel({ history, slots, coins }: AutoTradeHistoryPanelProps) {
  const [slotFilter, setSlotFilter] = useState<number | "all">("all");

  const filtered = useMemo(
    () => (slotFilter === "all" ? history : history.filter((order) => order.strategy_slot_id === slotFilter)),
    [history, slotFilter],
  );

  const koreanName = (symbol: string) => coins.find((coin) => coin.symbol === symbol)?.korean_name ?? symbol;

  return (
    <div className="dashboard-card trade-history-panel">
      <div className="dashboard-card-header">
        <p className="dashboard-card-label">자동매매 체결 내역</p>
        {slots.length > 0 && (
          <select
            className="wallet-date-input"
            value={slotFilter}
            onChange={(event) =>
              setSlotFilter(event.target.value === "all" ? "all" : Number(event.target.value))
            }
          >
            <option value="all">전체 전략</option>
            {slots.map((slot) => (
              <option key={slot.id} value={slot.id}>
                {koreanName(slot.coin_symbol)}
              </option>
            ))}
          </select>
        )}
      </div>
      {filtered.length === 0 ? (
        <p className="dashboard-empty-text">체결 내역이 없습니다.</p>
      ) : (
        <ul className="dashboard-trade-list">
          {filtered.map((order) => (
            <li key={order.id} className="trade-history-item">
              <span className={order.side === "buy" ? "dashboard-trade-badge is-buy" : "dashboard-trade-badge is-sell"}>
                {order.side === "buy" ? "매수" : "매도"}
              </span>
              <span>{koreanName(order.coin_symbol)}</span>
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
