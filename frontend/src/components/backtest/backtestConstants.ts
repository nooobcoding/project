import type { CandleInterval } from "../../types/candles";
import type { Indicator, StrategyType } from "../../types/strategySlots";

// SlotFormModal 등 07 화면의 각 파일이 라벨을 지역 상수로 따로 두는 것과 달리, 여기 4개
// 컴포넌트(설정 패널·결과 패널·저장/불러오기 모달)가 같은 라벨을 공유해야 해서 한 곳에 둔다.

export const STRATEGY_TYPE_LABEL: Record<StrategyType, string> = {
  trend: "추세추종",
  counter_trend: "역추세",
  grid: "그리드",
  dca: "DCA",
};

export const INDICATOR_LABEL: Record<Indicator, string> = {
  ma: "MA",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "볼린저밴드",
};

export const INTERVAL_LABEL: Record<CandleInterval, string> = {
  "1m": "1분봉",
  "10m": "10분봉",
  "30m": "30분봉",
  "1h": "1시간봉",
  "1d": "일봉",
};

// services/candles.py MAX_RANGE_DAYS와 1:1 대응 (06-backtesting.md 2.1-1절). 서버가 최종
// 방어선이고, 여기서는 Date Picker 범위 제한과 실행 버튼 비활성화용으로 미리 계산한다.
export const MAX_RANGE_DAYS: Record<CandleInterval, number> = {
  "1m": 7,
  "10m": 30,
  "30m": 90,
  "1h": 180,
  "1d": 1825,
};

// services/candles.py _LIMIT_LABELS와 1:1 대응 — 오류 문구에 그대로 쓴다.
export const RANGE_LIMIT_LABEL: Record<CandleInterval, string> = {
  "1m": "7일",
  "10m": "1개월",
  "30m": "3개월",
  "1h": "6개월",
  "1d": "5년",
};

export function rangeLimitErrorText(interval: CandleInterval): string {
  return `${INTERVAL_LABEL[interval]}은 최대 ${RANGE_LIMIT_LABEL[interval]}까지 조회할 수 있습니다.`;
}

function toDateOnly(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}

/** 두 날짜(YYYY-MM-DD) 사이의 봉단위별 최대 조회 기간 초과 여부 (양끝 포함이라 +1일). */
export function exceedsRangeLimit(interval: CandleInterval, startDate: string, endDate: string): boolean {
  const days = Math.round((toDateOnly(endDate).getTime() - toDateOnly(startDate).getTime()) / 86_400_000) + 1;
  return days > MAX_RANGE_DAYS[interval];
}

/** 오늘 날짜(YYYY-MM-DD, 로컬 타임존 기준 Date input 값과 맞춤). */
export function todayDateInput(): string {
  const now = new Date();
  const offsetMs = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offsetMs).toISOString().slice(0, 10);
}

/** `base`에서 `days`일을 뺀 날짜(YYYY-MM-DD). */
export function subtractDays(base: string, days: number): string {
  const date = toDateOnly(base);
  date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}

/** 저장된 결과를 불러올 때 NUMERIC 컬럼의 뒤따르는 0을 없앤다 (예: "10000000.0000" → "10000000",
 * "0.050" → "0.05"). 실행에 새로 쓴 값과 표시를 맞추기 위함이며 계산에는 영향이 없다. */
export function trimTrailingZeros(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}
