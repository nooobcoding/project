import { useMemo, useState } from "react";
import type { Coin } from "../../types/coins";

interface CoinSearchListProps {
  coins: Coin[];
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
  disabled?: boolean;
}

// 07-auto-trading.md 3-A "대상 코인" 선택 — 03-manual-trading의 CoinListPanel(검색창이 항상
// 목록 맨 위에 고정되고 그 아래를 스크롤하는 구조)과 동일한 방식으로 만든다. 네이티브 select는
// 이름/심볼 검색이 안 돼 코인이 많아지면 원하는 항목을 찾기 어렵다는 문제가 있었다.
export function CoinSearchList({ coins, selectedSymbol, onSelect, disabled }: CoinSearchListProps) {
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
    <div className="auto-coin-select">
      <input
        className="auth-input"
        placeholder="코인명/심볼 검색"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        disabled={disabled}
      />
      <ul className="auto-coin-select-list">
        {filtered.length === 0 ? (
          <li className="dashboard-add-coin-empty">일치하는 코인이 없습니다.</li>
        ) : (
          filtered.map((coin) => (
            <li
              key={coin.symbol}
              className={
                coin.symbol === selectedSymbol
                  ? "trade-coin-list-item is-selected"
                  : "trade-coin-list-item"
              }
              onClick={() => !disabled && onSelect(coin.symbol)}
            >
              <div className="trade-coin-list-name">
                <span>{coin.korean_name}</span>
                <span className="trade-coin-list-symbol">{coin.symbol}</span>
              </div>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
