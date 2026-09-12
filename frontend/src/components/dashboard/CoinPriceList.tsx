import type { PriceTick, WatchlistItem } from "../../types/dashboard";

const MAX_WATCHLIST_SIZE = 5;

interface CoinPriceListProps {
  items: WatchlistItem[];
  prices: Record<string, PriceTick>;
  onAddClick: () => void;
  onRemove: (symbol: string) => void;
}

export function CoinPriceList({ items, prices, onAddClick, onRemove }: CoinPriceListProps) {
  return (
    <div className="dashboard-card">
      <div className="dashboard-card-header">
        <p className="dashboard-card-label">주요 코인 시세</p>
        <button
          className="dashboard-chip-button"
          onClick={onAddClick}
          disabled={items.length >= MAX_WATCHLIST_SIZE}
        >
          + 추가
        </button>
      </div>
      {items.length === 0 ? (
        <p className="dashboard-empty-text">관심 코인을 추가해주세요.</p>
      ) : (
        <ul className="dashboard-price-list">
          {items.map((item) => {
            const tick = prices[item.coin_symbol];
            const changeRate = tick ? tick.signed_change_rate * 100 : 0;
            const changeClass =
              tick?.change === "RISE" ? "is-positive" : tick?.change === "FALL" ? "is-negative" : "";
            return (
              <li key={item.coin_symbol} className="dashboard-price-list-item">
                <span className="dashboard-coin-symbol">{item.coin_symbol}</span>
                <span>{tick ? Math.round(tick.trade_price).toLocaleString("ko-KR") : "-"}</span>
                <span className={changeClass}>
                  {tick ? `${changeRate > 0 ? "+" : ""}${changeRate.toFixed(2)}%` : "-"}
                </span>
                <button
                  className="dashboard-remove-button"
                  onClick={() => onRemove(item.coin_symbol)}
                  aria-label={`${item.coin_symbol} 관심 코인 제거`}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
