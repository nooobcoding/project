import type { PriceTick } from "../../types/dashboard";
import type { HoldingItem, PortfolioSummary } from "../../types/portfolio";

interface PortfolioSummaryCardsProps {
  summary: PortfolioSummary | null;
  holdings: HoldingItem[];
  prices: Record<string, PriceTick>;
  isLoading: boolean;
}

function won(value: number): string {
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

// 08-portfolio.md 2-A — 총손익·수익률은 서버가 계산하지 않는다. 실시간 시세로 코인 평가액을
// 재계산해 "총 손익 = 총평가금액 − 순투입원금"을 여기서 낸다 (평가손익 포함, realized_profit
// 합과는 다른 지표 — 문서 2-A 참고).
export function PortfolioSummaryCards({ summary, holdings, prices, isLoading }: PortfolioSummaryCardsProps) {
  if (isLoading || !summary) {
    return (
      <div className="backtest-metric-grid">
        <div className="backtest-metric-tile">불러오는 중...</div>
      </div>
    );
  }

  const krwBalance = Number(summary.krw_balance);
  const netDeposit = Number(summary.net_deposit);
  const coinValuation = holdings.reduce((sum, holding) => {
    const live = prices[holding.coin_symbol]?.trade_price;
    const price = live ?? Number(holding.current_price);
    return sum + Number(holding.quantity) * price;
  }, 0);
  const totalAsset = krwBalance + coinValuation;
  const totalProfit = totalAsset - netDeposit;
  const profitPct = netDeposit > 0 ? (totalProfit / netDeposit) * 100 : 0;
  const profitClass = totalProfit > 0 ? "is-positive" : totalProfit < 0 ? "is-negative" : "";

  return (
    <div className="backtest-metric-grid portfolio-summary-grid">
      <div className="backtest-metric-tile">
        <p className="dashboard-card-label">총 평가금액</p>
        <p className="backtest-metric-value">{won(totalAsset)}</p>
      </div>
      <div className="backtest-metric-tile">
        <p className="dashboard-card-label">총 손익</p>
        <p className={`backtest-metric-value ${profitClass}`}>
          {totalProfit > 0 ? "+" : ""}
          {won(totalProfit)}
        </p>
      </div>
      <div className="backtest-metric-tile">
        <p className="dashboard-card-label">수익률</p>
        <p className={`backtest-metric-value ${profitClass}`}>
          {profitPct > 0 ? "+" : ""}
          {profitPct.toFixed(2)}%
        </p>
      </div>
      <div className="backtest-metric-tile">
        <p className="dashboard-card-label">보유 원화</p>
        <p className="backtest-metric-value">{won(krwBalance)}</p>
      </div>
    </div>
  );
}
