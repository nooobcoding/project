// backend/app/schemas/backtest.py 1:1 대응 (docs/02-coding-conventions.md 9장)

import type { Indicator, StrategyParams, StrategyType } from "./strategySlots";

export interface BacktestTradeOut {
  side: "buy" | "sell";
  price: string;
  quantity: string;
  // 매도만 값을 갖는다 — 매수는 실현손익이 없다.
  profit: string | null;
  executed_at: string;
}

export interface EquityPointOut {
  at: string;
  asset: string;
}

export interface BacktestMetricsOut {
  total_return: string;
  final_asset: string;
  trade_count: number;
  win_rate: string;
  mdd: string;
  sharpe_ratio: string;
  benchmark_return: string;
  // 총수익률 − 벤치마크. DB에는 저장하지 않는 파생값이라 응답에만 있다.
  excess_return: string;
}

export interface BacktestRunInput {
  coin_symbol: string;
  strategy_type: StrategyType;
  indicator: Indicator | null;
  params: StrategyParams;
  start_date: string; // YYYY-MM-DD
  end_date: string;
  initial_capital: string;
  // % 단위 (예: "0.05" = 0.05%)
  fee_rate: string;
  slippage_rate: string;
  stop_loss_pct?: string;
  take_profit_pct?: string;
}

// /run 응답 = /results 저장 요청의 설정값 부분과 1:1로 겹친다 (백엔드가 그렇게 설계됨) —
// 실행 결과를 그대로 저장 요청에 되보낼 수 있다.
export interface BacktestRunResult {
  coin_symbol: string;
  strategy_type: StrategyType;
  indicator: Indicator | null;
  params: StrategyParams;
  start_date: string;
  end_date: string;
  initial_capital: string;
  fee_rate: string;
  slippage_rate: string;
  metrics: BacktestMetricsOut;
  equity_curve: EquityPointOut[];
  trades: BacktestTradeOut[];
}

export interface BacktestSaveInput extends BacktestRunResult {
  label: string;
}

export interface BacktestResultSummary {
  id: number;
  label: string;
  coin_symbol: string;
  strategy_type: StrategyType;
  indicator: Indicator | null;
  total_return: string;
  final_asset: string;
  created_at: string;
}

export interface BacktestResultDetail {
  id: number;
  label: string;
  created_at: string;
  coin_symbol: string;
  strategy_type: StrategyType;
  indicator: Indicator | null;
  params: StrategyParams;
  start_date: string;
  end_date: string;
  initial_capital: string;
  fee_rate: string;
  slippage_rate: string;
  metrics: BacktestMetricsOut;
  equity_curve: EquityPointOut[];
  trades: BacktestTradeOut[];
}
