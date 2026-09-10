import { CoinFilterDropdown } from "./CoinFilterDropdown";
import type { CoinRef, TradeItem, TradeSide, TradeSource } from "../../types/portfolio";

interface TradesPanelProps {
  items: TradeItem[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  side: TradeSide | null;
  source: TradeSource | null;
  coinSymbol: string | null;
  tradedCoins: CoinRef[];
  onSideChange: (side: TradeSide | null) => void;
  onSourceChange: (source: TradeSource | null) => void;
  onCoinChange: (symbol: string | null) => void;
  onPageChange: (page: number) => void;
  onExportCsv: () => void;
  isExporting: boolean;
}

function won(value: string): string {
  return `${Math.round(Number(value)).toLocaleString("ko-KR")}원`;
}

// 08-portfolio.md 2-B 거래 내역 — 필터 칩(전체/매수/매도/수동/자동, "전체"는 side·source를
// 함께 null로 되돌리는 것으로 배타 처리) + 코인별 드롭다운 + 목록 + 20건 페이지네이션 + CSV.
export function TradesPanel({
  items,
  total,
  page,
  pageSize,
  isLoading,
  side,
  source,
  coinSymbol,
  tradedCoins,
  onSideChange,
  onSourceChange,
  onCoinChange,
  onPageChange,
  onExportCsv,
  isExporting,
}: TradesPanelProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const isAll = side === null && source === null;

  return (
    <section className="wallet-panel portfolio-trades-panel">
      <div className="wallet-history-filters">
        <div className="wallet-filter-chip-row">
          <button
            type="button"
            className={isAll ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => {
              onSideChange(null);
              onSourceChange(null);
            }}
          >
            전체
          </button>
          <button
            type="button"
            className={side === "buy" ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => onSideChange("buy")}
          >
            매수
          </button>
          <button
            type="button"
            className={side === "sell" ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => onSideChange("sell")}
          >
            매도
          </button>
          <button
            type="button"
            className={source === "manual" ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => onSourceChange("manual")}
          >
            수동
          </button>
          <button
            type="button"
            className={source === "auto" ? "dashboard-chip-button is-active" : "dashboard-chip-button"}
            onClick={() => onSourceChange("auto")}
          >
            자동
          </button>
        </div>
        <CoinFilterDropdown coins={tradedCoins} selectedSymbol={coinSymbol} onSelect={onCoinChange} />
      </div>

      {isLoading ? (
        <p className="dashboard-empty-text">불러오는 중...</p>
      ) : items.length === 0 ? (
        <p className="dashboard-empty-text">해당 조건의 거래 내역이 없습니다.</p>
      ) : (
        <ul className="portfolio-trades-list">
          <li className="portfolio-trades-item portfolio-trades-header">
            <span>유형</span>
            <span>구분</span>
            <span>코인</span>
            <span>체결가</span>
            <span>수량</span>
            <span>체결일시</span>
          </li>
          {items.map((item) => (
            <li key={item.id} className="portfolio-trades-item">
              <span className={item.side === "buy" ? "portfolio-side-badge is-buy" : "portfolio-side-badge is-sell"}>
                {item.side === "buy" ? "매수" : "매도"}
              </span>
              <span
                className={
                  item.source === "auto" ? "portfolio-source-badge is-auto" : "portfolio-source-badge is-manual"
                }
              >
                {item.source === "auto" ? "자동" : "수동"}
              </span>
              <span className="portfolio-trades-coin">
                <span>{item.korean_name}</span>
                <span className="trade-coin-list-symbol">{item.coin_symbol}</span>
              </span>
              <span>{won(item.price)}</span>
              <span>{Number(item.quantity).toLocaleString("ko-KR", { maximumFractionDigits: 8 })}</span>
              <span className="trade-history-time">{new Date(item.filled_at).toLocaleString("ko-KR")}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="portfolio-trades-footer">
        <button type="button" className="dashboard-chip-button" onClick={onExportCsv} disabled={isExporting}>
          {isExporting ? "내보내는 중..." : "CSV 내보내기"}
        </button>
        <div className="wallet-pagination">
          <button
            type="button"
            className="dashboard-chip-button"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            이전
          </button>
          <span className="wallet-pagination-label">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className="dashboard-chip-button"
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
          >
            다음
          </button>
        </div>
      </div>
    </section>
  );
}
