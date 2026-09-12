import type { PriceTick } from "../../types/dashboard";
import type { HoldingItem } from "../../types/portfolio";

interface HoldingsPanelProps {
  items: HoldingItem[];
  prices: Record<string, PriceTick>;
  isLoading: boolean;
}

function won(value: number): string {
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

// 08-portfolio.md 2-B 보유 자산 현황 — holdings × 실시간 시세. 서버 응답의 current_price/
// valuation/profit/profit_pct는 조회 시점 스냅샷이라, 시세 캐시가 있는 코인은 실시간 값으로
// 재계산한다(PortfolioSummaryCards와 동일 방침).
export function HoldingsPanel({ items, prices, isLoading }: HoldingsPanelProps) {
  return (
    <section className="wallet-panel portfolio-holdings-panel">
      <h2 className="portfolio-panel-title">보유 자산</h2>

      {isLoading ? (
        <p className="dashboard-empty-text">불러오는 중...</p>
      ) : items.length === 0 ? (
        <p className="dashboard-empty-text">보유 중인 코인이 없습니다.</p>
      ) : (
        <ul className="portfolio-holdings-list">
          <li className="portfolio-holdings-item portfolio-holdings-header">
            <span>코인</span>
            <span>수량</span>
            <span>평균매수가</span>
            <span>현재가</span>
            <span>평가금액</span>
            <span>손익</span>
          </li>
          {items.map((item) => {
            const quantity = Number(item.quantity);
            const avgBuyPrice = Number(item.avg_buy_price);
            const live = prices[item.coin_symbol]?.trade_price;
            const currentPrice = live ?? Number(item.current_price);
            const valuation = quantity * currentPrice;
            const cost = quantity * avgBuyPrice;
            const profit = valuation - cost;
            const profitPct = cost > 0 ? (profit / cost) * 100 : 0;
            const profitClass = profit > 0 ? "is-positive" : profit < 0 ? "is-negative" : "";

            return (
              <li key={item.coin_symbol} className="portfolio-holdings-item">
                <span className="portfolio-holdings-name">
                  <span>{item.korean_name}</span>
                  <span className="trade-coin-list-symbol">{item.coin_symbol}</span>
                </span>
                <span>{quantity.toLocaleString("ko-KR", { maximumFractionDigits: 8 })}</span>
                <span>{won(avgBuyPrice)}</span>
                <span>{won(currentPrice)}</span>
                <span>{won(valuation)}</span>
                <span className={profitClass}>
                  {profit > 0 ? "+" : ""}
                  {won(profit)} ({profitPct > 0 ? "+" : ""}
                  {profitPct.toFixed(2)}%)
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
