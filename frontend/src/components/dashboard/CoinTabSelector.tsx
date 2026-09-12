import type { WatchlistItem } from "../../types/dashboard";

interface CoinTabSelectorProps {
  items: WatchlistItem[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}

// 관심 코인 추가는 CoinPriceList의 AddCoinSearch로 일원화되어 있다 (중복 버튼 제거).
export function CoinTabSelector({ items, selectedSymbol, onSelect }: CoinTabSelectorProps) {
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
    </div>
  );
}
