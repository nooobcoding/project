// backend/app/schemas/strategy_slots.py 1:1 대응 (docs/02-coding-conventions.md 9장)
//
// DCA(dca)는 07 Step 5에서 strategy_engine이 구현된 뒤 이 파일에도 타입을 추가한다 —
// 지금은 백엔드가 trend/counter_trend/grid만 받으므로 여기도 동일하게 맞춘다
// (backend/app/schemas/strategy_slots.py 상단 주석과 같은 이유).

import type { CandleInterval } from "./candles";

export type StrategyType = "trend" | "counter_trend" | "grid";
export type Indicator = "ma" | "rsi" | "macd" | "bollinger";

export interface MaTrendParams {
  interval: CandleInterval;
  short_period: number;
  long_period: number;
}

export interface MaCounterTrendParams {
  interval: CandleInterval;
  short_period: number;
  long_period: number;
  deviation_pct: number;
}

export interface RsiTrendParams {
  interval: CandleInterval;
  period: number;
  threshold: number;
}

export interface RsiCounterTrendParams {
  interval: CandleInterval;
  period: number;
  oversold: number;
  overbought: number;
}

export interface MacdParams {
  interval: CandleInterval;
  short_period: number;
  long_period: number;
  signal_period: number;
}

export interface BollingerParams {
  interval: CandleInterval;
  period: number;
  std_multiplier: number;
}

export interface GridParams {
  interval: CandleInterval;
  lower_price: number;
  upper_price: number;
  grid_count: number;
}

export type StrategyParams =
  | MaTrendParams
  | MaCounterTrendParams
  | RsiTrendParams
  | RsiCounterTrendParams
  | MacdParams
  | BollingerParams
  | GridParams;

// strategy_slots.state — 01-erd.md 3.6절. 워커/체결훅만 쓰고 화면은 읽기 전용으로 참고한다
// (삭제 확인 모달의 잔여 수량 표시, 07-auto-trading.md 4.2절).
export interface SlotPosition {
  quantity: string;
  avg_price: string;
  entry_at: string;
}

export interface GridLine {
  price: string;
  filled: boolean;
  quantity: string;
}

export interface SlotState {
  position?: SlotPosition;
  last_evaluated_candle_at?: string;
  grid?: { lines: GridLine[] };
}

export interface StrategySlot {
  id: number;
  coin_symbol: string;
  strategy_type: StrategyType;
  // 그리드는 지표를 쓰지 않아 null이다.
  indicator: Indicator | null;
  params: StrategyParams;
  invest_amount: string;
  stop_loss_pct: string | null;
  take_profit_pct: string | null;
  state: SlotState;
  is_active: boolean;
  created_at: string;
}

export interface StrategySlotWriteInput {
  coin_symbol: string;
  strategy_type: StrategyType;
  indicator: Indicator | null;
  params: StrategyParams;
  invest_amount: string;
  stop_loss_pct?: string;
  take_profit_pct?: string;
}

export interface SlotDeletionResult {
  coin_symbol: string;
  korean_name: string;
  remaining_quantity: string;
}

export interface SlotSignal {
  signal: "buy" | "sell" | null;
  evaluated_at: string;
}
