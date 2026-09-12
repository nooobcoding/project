import { apiFetch } from "./client";
import type {
  BacktestResultDetail,
  BacktestResultSummary,
  BacktestRunInput,
  BacktestRunResult,
  BacktestSaveInput,
} from "../types/backtest";

// 동기 실행 — 결과만 반환하고 저장하지 않는다 (06-backtesting.md 6장). 최대 60초까지 걸릴 수
// 있어(services/backtest.py RUN_TIMEOUT_SECONDS) 다른 API 호출과 달리 응답이 느릴 수 있다.
export function runBacktest(token: string, input: BacktestRunInput): Promise<BacktestRunResult> {
  return apiFetch<BacktestRunResult>("/api/backtest/run", {
    method: "POST",
    token,
    body: JSON.stringify(input),
  });
}

export function saveBacktestResult(
  token: string,
  input: BacktestSaveInput,
): Promise<BacktestResultDetail> {
  return apiFetch<BacktestResultDetail>("/api/backtest/results", {
    method: "POST",
    token,
    body: JSON.stringify(input),
  });
}

export function getBacktestResults(token: string): Promise<BacktestResultSummary[]> {
  return apiFetch<BacktestResultSummary[]>("/api/backtest/results", { token });
}

export function getBacktestResult(token: string, id: number): Promise<BacktestResultDetail> {
  return apiFetch<BacktestResultDetail>(`/api/backtest/results/${id}`, { token });
}
