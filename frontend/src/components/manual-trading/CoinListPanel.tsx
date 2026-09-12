import { useMemo, useState } from "react";
import type { PriceTick } from "../../types/dashboard";
import type { Coin } from "../../types/coins";

interface CoinListPanelProps {
  coins: Coin[];
  prices: Record<string, PriceTick>;
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}

// 03-manual-trading.md 2-A — 1열 코인 목록. 자동매매 배지는 07-auto-trading 미구현이라
// 넣지 않는다(잠금배너와 마찬가지로 07 완료 후 추가).
export function CoinListPanel({ coins, prices, selectedSymbol, onSelect }: CoinListPanelProps) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const keyword = query.trim().toUpperCase();
    if (!keyword) return coins;
    return coins.filter(
      (coin) =>
        coin.symbol.includes(keyword) ||
        coin.korean_name.toUpperCase().includes(keyword) ||
        coin.english_name.toUpperCase().includes(keyword),
    );
  }, [coins, query]);

  return (
    <div className="trade-panel trade-coin-list-panel">
      <input
        className="auth-input"
        placeholder="코인명/심볼 검색"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ul className="trade-coin-list">
        {filtered.map((coin) => {
          const tick = prices[coin.symbol];
          const changeRate = tick ? tick.signed_change_rate * 100 : 0;
          const changeClass =
            tick?.change === "RISE" ? "is-positive" : tick?.change === "FALL" ? "is-negative" : "";
          return (
            <li
              key={coin.symbol}
              className={
                coin.symbol === selectedSymbol
                  ? "trade-coin-list-item is-selected"
                  : "trade-coin-list-item"
              }
              onClick={() => onSelect(coin.symbol)}
            >
              <div className="trade-coin-list-name">
                <span>{coin.korean_name}</span>
                <span className="trade-coin-list-symbol">{coin.symbol}</span>
              </div>
              <div className="trade-coin-list-price">
                <span>{tick ? Math.round(tick.trade_price).toLocaleString("ko-KR") : "-"}</span>
                <span className={changeClass}>
                  {tick ? `${changeRate > 0 ? "+" : ""}${changeRate.toFixed(2)}%` : "-"}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
