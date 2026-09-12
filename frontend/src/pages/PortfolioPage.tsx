import { useMemo, useState } from "react";
import { downloadPortfolioTradesCsv } from "../api/portfolio";
import { AllocationDonutChart } from "../components/portfolio/AllocationDonutChart";
import { HoldingsPanel } from "../components/portfolio/HoldingsPanel";
import { PerformanceReportCard } from "../components/portfolio/PerformanceReportCard";
import { PortfolioSummaryCards } from "../components/portfolio/PortfolioSummaryCards";
import { TradesPanel } from "../components/portfolio/TradesPanel";
import { Toast } from "../components/Toast";
import { useAuth } from "../hooks/useAuth";
import { usePortfolioHoldings } from "../hooks/usePortfolioHoldings";
import { usePortfolioReport } from "../hooks/usePortfolioReport";
import { usePortfolioSummary } from "../hooks/usePortfolioSummary";
import { usePortfolioTrades } from "../hooks/usePortfolioTrades";
import { usePriceStream } from "../hooks/usePriceStream";
import type { ReportPeriod, TradeSide, TradeSource } from "../types/portfolio";

// SCR-06 — 포트폴리오 (docs/features/08-portfolio.md): 상단 4카드 / 하단 2컬럼
// (좌: 보유자산+거래내역 / 우: 도넛차트+성과리포트).
export function PortfolioPage() {
  const { token } = useAuth();
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [side, setSide] = useState<TradeSide | null>(null);
  const [source, setSource] = useState<TradeSource | null>(null);
  const [coinSymbol, setCoinSymbol] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [period, setPeriod] = useState<ReportPeriod>("1m");
  const [isExporting, setIsExporting] = useState(false);

  const { summary, isLoading: isSummaryLoading } = usePortfolioSummary();
  const { items: holdings, isLoading: isHoldingsLoading } = usePortfolioHoldings();
  const {
    items: trades,
    total,
    tradedCoins,
    pageSize,
    isLoading: isTradesLoading,
  } = usePortfolioTrades({ side, source, coinSymbol, page });
  const { report, isLoading: isReportLoading } = usePortfolioReport(period);

  const holdingSymbols = useMemo(() => holdings.map((item) => item.coin_symbol), [holdings]);
  const { prices } = usePriceStream(holdingSymbols);

  const handleExportCsv = async () => {
    if (!token) return;
    setIsExporting(true);
    try {
      await downloadPortfolioTradesCsv(token, { side, source, coinSymbol });
    } catch (error) {
      setToastMessage(error instanceof Error ? error.message : "파일 생성 중 오류가 발생했습니다. 다시 시도해주세요.");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="wallet-page">
      <PortfolioSummaryCards
        summary={summary}
        holdings={holdings}
        prices={prices}
        isLoading={isSummaryLoading}
      />

      <div className="portfolio-layout">
        <div className="portfolio-column">
          <HoldingsPanel items={holdings} prices={prices} isLoading={isHoldingsLoading} />
          <TradesPanel
            items={trades}
            total={total}
            page={page}
            pageSize={pageSize}
            isLoading={isTradesLoading}
            side={side}
            source={source}
            coinSymbol={coinSymbol}
            tradedCoins={tradedCoins}
            onSideChange={(value) => {
              setSide(value);
              setPage(1);
            }}
            onSourceChange={(value) => {
              setSource(value);
              setPage(1);
            }}
            onCoinChange={(value) => {
              setCoinSymbol(value);
              setPage(1);
            }}
            onPageChange={setPage}
            onExportCsv={handleExportCsv}
            isExporting={isExporting}
          />
        </div>
        <div className="portfolio-column">
          <section className="wallet-panel">
            <h2 className="portfolio-panel-title">자산 배분</h2>
            <AllocationDonutChart
              krwBalance={summary ? Number(summary.krw_balance) : 0}
              holdings={holdings}
              prices={prices}
            />
          </section>
          <PerformanceReportCard
            report={report}
            period={period}
            isLoading={isReportLoading}
            onPeriodChange={setPeriod}
          />
        </div>
      </div>

      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
