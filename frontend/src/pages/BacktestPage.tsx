import { useState } from "react";
import { getBacktestResult, runBacktest, saveBacktestResult } from "../api/backtest";
import { ApiError } from "../api/client";
import { BacktestLoadModal } from "../components/backtest/BacktestLoadModal";
import { BacktestResultPanel } from "../components/backtest/BacktestResultPanel";
import { BacktestSaveModal } from "../components/backtest/BacktestSaveModal";
import { BacktestSettingsPanel } from "../components/backtest/BacktestSettingsPanel";
import { trimTrailingZeros } from "../components/backtest/backtestConstants";
import { useAuth } from "../hooks/useAuth";
import { useBacktestResults } from "../hooks/useBacktestResults";
import { useCoins } from "../hooks/useCoins";
import type { BacktestRunInput, BacktestRunResult } from "../types/backtest";

const RUN_ERROR_FALLBACK = "백테스트 실행 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.";

// SCR-05 — 백테스팅 (docs/features/06-backtesting.md). 2컬럼 — 설정 패널(260px, 좌) /
// 결과 패널(우). ManualTradingPage/AutoTradingPage와 같은 패턴으로 페이지가 실행·저장·불러오기
// 상태를 전부 소유하고 하위 패널은 props만 받는다.
export function BacktestPage() {
  const { token } = useAuth();
  const { coins } = useCoins();
  const { results, isLoading: isResultsLoading, refresh: refreshResults } = useBacktestResults();

  const [runResult, setRunResult] = useState<BacktestRunResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // 불러온 결과의 설정값 — BacktestSettingsPanel을 이 값으로 다시 마운트시켜 폼을 채운다
  // (key={loadedConfig?.id}).
  const [loadedConfig, setLoadedConfig] = useState<{ id: number; input: BacktestRunInput } | null>(null);

  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
  const [isLoadModalOpen, setIsLoadModalOpen] = useState(false);

  const handleRun = async (input: BacktestRunInput) => {
    if (!token) return;
    setIsRunning(true);
    setRunError(null);
    try {
      const result = await runBacktest(token, input);
      setRunResult(result);
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : RUN_ERROR_FALLBACK);
    } finally {
      setIsRunning(false);
    }
  };

  const handleSave = async (label: string) => {
    if (!token || !runResult) return;
    await saveBacktestResult(token, { ...runResult, label });
    await refreshResults();
    setIsSaveModalOpen(false);
  };

  const handleLoadResult = async (id: number) => {
    if (!token) return;
    const detail = await getBacktestResult(token, id);
    setLoadedConfig({
      id: detail.id,
      input: {
        coin_symbol: detail.coin_symbol,
        strategy_type: detail.strategy_type,
        indicator: detail.indicator,
        params: detail.params,
        start_date: detail.start_date,
        end_date: detail.end_date,
        initial_capital: trimTrailingZeros(detail.initial_capital),
        fee_rate: trimTrailingZeros(detail.fee_rate),
        slippage_rate: trimTrailingZeros(detail.slippage_rate),
      },
    });
    setRunResult(detail);
    setRunError(null);
    setIsLoadModalOpen(false);
  };

  return (
    <div className="dashboard-page">
      <div className="backtest-grid">
        <BacktestSettingsPanel
          key={loadedConfig?.id ?? "fresh"}
          coins={coins}
          onRun={handleRun}
          isRunning={isRunning}
          initialConfig={loadedConfig?.input}
        />
        <BacktestResultPanel
          result={runResult}
          isRunning={isRunning}
          error={runError}
          onOpenSave={() => setIsSaveModalOpen(true)}
          onOpenLoad={() => setIsLoadModalOpen(true)}
        />
      </div>

      {isSaveModalOpen && runResult && (
        <BacktestSaveModal
          result={runResult}
          coins={coins}
          onSave={handleSave}
          onClose={() => setIsSaveModalOpen(false)}
        />
      )}

      {isLoadModalOpen && (
        <BacktestLoadModal
          results={results}
          isLoading={isResultsLoading}
          onSelect={handleLoadResult}
          onClose={() => setIsLoadModalOpen(false)}
        />
      )}
    </div>
  );
}
