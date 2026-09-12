import { useState } from "react";
import { BacktestEquityChart } from "./BacktestEquityChart";
import { BacktestTradeModal } from "./BacktestTradeModal";
import type { BacktestRunResult, BacktestTradeOut } from "../../types/backtest";

interface BacktestResultPanelProps {
  result: BacktestRunResult | null;
  isRunning: boolean;
  error: string | null;
  onOpenSave: () => void;
  onOpenLoad: () => void;
}

function pct(value: string): string {
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

// final_asset은 NUMERIC(20,4)라 소수 4자리까지 올 수 있다 — 원화 표시에는 정수만 보여준다.
function won(value: string): string {
  return `${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
}

// 06-backtesting.md 3-B절 — 성과지표 7개 그리드 + 수익 곡선 + 저장/불러오기.
export function BacktestResultPanel({
  result,
  isRunning,
  error,
  onOpenSave,
  onOpenLoad,
}: BacktestResultPanelProps) {
  const [selectedTrades, setSelectedTrades] = useState<BacktestTradeOut[] | null>(null);

  return (
    <section className="backtest-panel backtest-result-panel">
      <div className="backtest-result-actions">
        <button type="button" className="dashboard-chip-button" onClick={onOpenLoad}>
          불러오기
        </button>
        <button type="button" className="dashboard-chip-button" onClick={onOpenSave} disabled={!result}>
          결과 저장
        </button>
      </div>

      {error && <p className="auth-error-message">{error}</p>}

      {isRunning && !result && <p className="dashboard-empty-text">백테스트를 실행하는 중입니다...</p>}

      {!isRunning && !result && !error && (
        <p className="dashboard-empty-text">설정을 마치고 실행 버튼을 눌러주세요.</p>
      )}

      {result && (
        <>
          <div className="backtest-metric-grid">
            <MetricTile label="총수익률" value={pct(result.metrics.total_return)} />
            <MetricTile label="최종자산" value={won(result.metrics.final_asset)} />
            <MetricTile label="거래횟수" value={`${result.metrics.trade_count}건`} />
            <MetricTile label="승률" value={`${result.metrics.win_rate}%`} />
            <MetricTile label="MDD" value={`${result.metrics.mdd}%`} />
            <MetricTile label="Sharpe" value={result.metrics.sharpe_ratio} />
            <MetricTile
              label="벤치마크 대비"
              value={pct(result.metrics.excess_return)}
              caption={`Buy&Hold ${pct(result.metrics.benchmark_return)}`}
            />
          </div>

          <BacktestEquityChart
            equityCurve={result.equity_curve}
            trades={result.trades}
            onSelectTrades={setSelectedTrades}
          />
        </>
      )}

      {selectedTrades && (
        <BacktestTradeModal trades={selectedTrades} onClose={() => setSelectedTrades(null)} />
      )}
    </section>
  );
}

function MetricTile({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <div className="backtest-metric-tile">
      <p className="dashboard-card-label">{label}</p>
      <p className="backtest-metric-value">{value}</p>
      {caption && <p className="backtest-metric-caption">{caption}</p>}
    </div>
  );
}
