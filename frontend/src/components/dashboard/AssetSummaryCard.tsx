import type { DashboardSummary } from "../../types/dashboard";

interface AssetSummaryCardProps {
  summary: DashboardSummary | null;
  isLoading: boolean;
}

function formatKrw(value: number): string {
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

export function AssetSummaryCard({ summary, isLoading }: AssetSummaryCardProps) {
  if (isLoading || !summary) {
    return <div className="dashboard-card">불러오는 중...</div>;
  }

  const krwBalance = Number(summary.krw_balance);
  const coinValuation = Number(summary.coin_valuation);
  const profitPct = Number(summary.profit_pct);
  const totalAsset = krwBalance + coinValuation;
  const profitClass = profitPct > 0 ? "is-positive" : profitPct < 0 ? "is-negative" : "";

  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">총 평가금액</p>
      <p className="dashboard-asset-total">{formatKrw(totalAsset)}</p>
      {/* 08-portfolio의 "총 손익"(누적 순투입원금 기준)과 다른, 전일 대비 평가손익 지표 (02-dashboard.md 2-A) */}
      <p className={`dashboard-profit-pct ${profitClass}`}>
        전일 대비 {profitPct > 0 ? "+" : ""}
        {profitPct.toFixed(2)}%
      </p>
      <div className="dashboard-mini-cards">
        <div className="dashboard-mini-card">
          <p className="dashboard-card-label">보유 원화</p>
          <p>{formatKrw(krwBalance)}</p>
        </div>
        <div className="dashboard-mini-card">
          <p className="dashboard-card-label">코인 평가액</p>
          <p>{formatKrw(coinValuation)}</p>
        </div>
      </div>
    </div>
  );
}
