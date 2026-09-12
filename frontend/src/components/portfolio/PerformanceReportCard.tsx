import type { PortfolioReport, ReportPeriod } from "../../types/portfolio";

interface PerformanceReportCardProps {
  report: PortfolioReport | null;
  period: ReportPeriod;
  isLoading: boolean;
  onPeriodChange: (period: ReportPeriod) => void;
}

const PERIOD_OPTIONS: { value: ReportPeriod; label: string }[] = [
  { value: "1m", label: "1개월" },
  { value: "3m", label: "3개월" },
  { value: "6m", label: "6개월" },
  { value: "1y", label: "1년" },
  { value: "all", label: "전체" },
];

function won(value: string): string {
  const n = Number(value);
  return `${n > 0 ? "+" : ""}${Math.round(n).toLocaleString("ko-KR")}원`;
}

// 08-portfolio.md 2-C 성과 분석 리포트 — 기간 셀렉트 + 가장 많이 거래한 코인 + 월별 수익
// (FR-P04, orders.realized_profit 합계 — 미실현 평가손익은 포함하지 않는다).
export function PerformanceReportCard({ report, period, isLoading, onPeriodChange }: PerformanceReportCardProps) {
  return (
    <section className="wallet-panel portfolio-report-panel">
      <div className="portfolio-report-header">
        <h2 className="portfolio-panel-title">성과 분석 리포트</h2>
        <select
          className="wallet-date-input"
          value={period}
          onChange={(event) => onPeriodChange(event.target.value as ReportPeriod)}
        >
          {PERIOD_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {isLoading || !report ? (
        <p className="dashboard-empty-text">불러오는 중...</p>
      ) : (
        <>
          <div className="portfolio-report-row">
            <span className="dashboard-card-label">가장 많이 거래한 코인</span>
            <span>{report.most_traded_coin ? report.most_traded_coin.korean_name : "거래 내역 없음"}</span>
          </div>

          <div className="portfolio-report-row">
            <span className="dashboard-card-label">월별 수익</span>
          </div>
          {report.monthly_profits.length === 0 ? (
            <p className="dashboard-empty-text">해당 기간의 매도 체결이 없습니다.</p>
          ) : (
            <ul className="portfolio-monthly-list">
              {report.monthly_profits.map((item) => {
                const profitClass = Number(item.profit) > 0 ? "is-positive" : Number(item.profit) < 0 ? "is-negative" : "";
                return (
                  <li key={item.month} className="portfolio-monthly-item">
                    <span>{item.month}</span>
                    <span className={profitClass}>{won(item.profit)}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
