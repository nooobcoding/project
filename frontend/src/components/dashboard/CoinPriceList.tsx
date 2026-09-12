import type { Coin } from "../../types/coins";
import type { PriceTick, WatchlistItem } from "../../types/dashboard";
import { AddCoinSearch } from "./AddCoinSearch";

const MAX_WATCHLIST_SIZE = 5;

interface CoinPriceListProps {
  items: WatchlistItem[];
  prices: Record<string, PriceTick>;
  coins: Coin[];
  onAdd: (symbol: string) => Promise<void>;
  onRemove: (symbol: string) => void;
}

export function CoinPriceList({ items, prices, coins, onAdd, onRemove }: CoinPriceListProps) {
  return (
    <div className="dashboard-card">
      <div className="dashboard-card-header">
        <p className="dashboard-card-label">주요 코인 시세</p>
        <AddCoinSearch
          coins={coins}
          excludeSymbols={items.map((item) => item.coin_symbol)}
          disabled={items.length >= MAX_WATCHLIST_SIZE}
          onAdd={onAdd}
        />
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
