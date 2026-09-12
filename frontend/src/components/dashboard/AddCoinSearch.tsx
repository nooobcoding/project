import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import type { Coin } from "../../types/coins";

const MAX_RESULTS = 8;

interface AddCoinSearchProps {
  coins: Coin[];
  excludeSymbols: string[];
  disabled: boolean;
  onAdd: (symbol: string) => Promise<void>;
}

// 02-dashboard.md 3장 — 모달 대신 버튼 바로 아래 붙는 검색 드롭다운으로 관심 코인을 추가한다.
// 심볼을 정확히 몰라도 이름/심볼 일부만 입력하면 후보가 뜨고, 클릭하면 바로 추가된다.
export function AddCoinSearch({ coins, excludeSymbols, disabled, onAdd }: AddCoinSearchProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("mousedown", handleOutsideClick);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [isOpen]);

  const openPopover = () => {
    setIsOpen(true);
    setQuery("");
    setError(undefined);
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const trimmedQuery = query.trim().toUpperCase();
  const results = trimmedQuery
    ? coins
        .filter((coin) => !excludeSymbols.includes(coin.symbol))
        .filter(
          (coin) =>
            coin.symbol.includes(trimmedQuery) ||
            coin.korean_name.toUpperCase().includes(trimmedQuery) ||
            coin.english_name.toUpperCase().includes(trimmedQuery),
        )
        .slice(0, MAX_RESULTS)
    : [];

  const handleSelect = async (symbol: string) => {
    setIsSubmitting(true);
    setError(undefined);
    try {
      await onAdd(symbol);
      setIsOpen(false);
      setQuery("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "관심 코인 추가에 실패했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-add-coin" ref={containerRef}>
      <button
        type="button"
        className="dashboard-chip-button"
        onClick={() => (isOpen ? setIsOpen(false) : openPopover())}
        disabled={disabled}
      >
        + 추가
      </button>
      {isOpen && (
        <div className="dashboard-add-coin-popover">
          <input
            ref={inputRef}
            className="auth-input"
            placeholder="코인명/심볼 검색"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {error && <p className="auth-error-message">{error}</p>}
          {trimmedQuery && (
            <ul className="dashboard-add-coin-results">
              {results.length === 0 ? (
                <li className="dashboard-add-coin-empty">일치하는 코인이 없습니다.</li>
              ) : (
                results.map((coin) => (
                  <li key={coin.symbol}>
                    <button
                      type="button"
                      className="dashboard-add-coin-result-item"
                      onClick={() => handleSelect(coin.symbol)}
                      disabled={isSubmitting}
                    >
                      <span>{coin.korean_name}</span>
                      <span className="trade-coin-list-symbol">{coin.symbol}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
