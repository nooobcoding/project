import type { WatchlistItem } from "../../types/dashboard";

const MAX_WATCHLIST_SIZE = 5;

interface CoinTabSelectorProps {
  items: WatchlistItem[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
  onAddClick: () => void;
}

export function CoinTabSelector({ items, selectedSymbol, onSelect, onAddClick }: CoinTabSelectorProps) {
  return (
    <div className="dashboard-tab-row">
      {items.map((item) => (
        <button
          key={item.coin_symbol}
          className={item.coin_symbol === selectedSymbol ? "dashboard-tab is-active" : "dashboard-tab"}
          onClick={() => onSelect(item.coin_symbol)}
        >
          {item.coin_symbol}
        </button>
      ))}
      {items.length < MAX_WATCHLIST_SIZE && (
        <button className="dashboard-tab dashboard-tab-add" onClick={onAddClick}>
          + 추가
        </button>
      )}
    </div>
  );
}
