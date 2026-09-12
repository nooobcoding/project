import type { OrderBookSnapshot } from "../../types/orderbook";

interface OrderBookPanelProps {
  orderBook: OrderBookSnapshot | null;
  currentPrice: number | null;
  onLevelClick: (price: number) => void;
}

// 03-manual-trading.md 2-C — 매도호가 10단(파랑)/현재가/매수호가 10단(빨강). 클릭 시 주문가격 자동입력.
export function OrderBookPanel({ orderBook, currentPrice, onLevelClick }: OrderBookPanelProps) {
  if (!orderBook) {
    return <div className="dashboard-card trade-orderbook-panel">호가 불러오는 중...</div>;
  }

  const units = orderBook.orderbook_units.slice(0, 10);
  const asks = [...units].reverse();

  return (
    <div className="dashboard-card trade-orderbook-panel">
      <ul className="trade-orderbook-list">
        {asks.map((unit) => (
          <li
            key={`ask-${unit.ask_price}`}
            className="trade-orderbook-row is-ask"
            onClick={() => onLevelClick(unit.ask_price)}
          >
            <span>{unit.ask_price.toLocaleString("ko-KR")}</span>
            <span>{unit.ask_size.toFixed(4)}</span>
          </li>
        ))}
      </ul>
      <div className="trade-orderbook-current-price">
        {currentPrice ? Math.round(currentPrice).toLocaleString("ko-KR") : "-"}
      </div>
      <ul className="trade-orderbook-list">
        {units.map((unit) => (
          <li
            key={`bid-${unit.bid_price}`}
            className="trade-orderbook-row is-bid"
            onClick={() => onLevelClick(unit.bid_price)}
          >
            <span>{unit.bid_price.toLocaleString("ko-KR")}</span>
            <span>{unit.bid_size.toFixed(4)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
