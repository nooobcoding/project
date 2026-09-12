import { useState } from "react";
import { CoinSearchList } from "../auto-trading/CoinSearchList";
import type { CoinRef } from "../../types/portfolio";

interface CoinFilterDropdownProps {
  coins: CoinRef[];
  selectedSymbol: string | null;
  onSelect: (symbol: string | null) => void;
}

// 08-portfolio.md 2-B "코인별 필터" — CoinSearchList(07-auto-trading)를 그대로 재사용하되,
// 그 컴포넌트는 "선택 해제" 개념이 없어(항상 무언가 선택된 상태를 가정) 팝오버 맨 위에
// "전체 코인" 항목을 얹어 필터 해제 동선을 추가한다. 목록은 실제 거래한 적 있는 코인만 받는다
// (전체 상장 코인이 아님).
export function CoinFilterDropdown({ coins, selectedSymbol, onSelect }: CoinFilterDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);

  const selectedLabel = selectedSymbol
    ? coins.find((coin) => coin.symbol === selectedSymbol)?.korean_name ?? selectedSymbol
    : "전체 코인";

  const pseudoCoins = coins.map((coin) => ({
    symbol: coin.symbol,
    korean_name: coin.korean_name,
    english_name: "",
    current_price: null,
    change_rate: null,
  }));

  return (
    <div className="dashboard-add-coin portfolio-coin-filter">
      <button type="button" className="dashboard-chip-button" onClick={() => setIsOpen((prev) => !prev)}>
        {selectedLabel} ▾
      </button>
      {isOpen && (
        <div className="dashboard-add-coin-popover">
          <button
            type="button"
            className="dashboard-add-coin-result-item"
            onClick={() => {
              onSelect(null);
              setIsOpen(false);
            }}
          >
            전체 코인
          </button>
          <CoinSearchList
            coins={pseudoCoins}
            selectedSymbol={selectedSymbol ?? ""}
            onSelect={(symbol) => {
              onSelect(symbol);
              setIsOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
