import type {
  BollingerParams,
  Indicator,
  MacdParams,
  MaCounterTrendParams,
  MaTrendParams,
  RsiCounterTrendParams,
  RsiTrendParams,
  StrategyParams,
  StrategyType,
} from "../../types/strategySlots";

// 07-auto-trading.md 3-C "전략 미리보기 카드" — 현재 폼의 매수·매도 조건을 06-backtesting.md
// 2.2절 표 그대로 문장으로 옮긴다. 백엔드 signals.py의 판정 로직과 반드시 같은 말을 해야 하므로
// 그 파일의 각 함수 docstring과 1:1로 대응시킨다.
export function buildConditionText(
  strategyType: StrategyType,
  indicator: Indicator,
  params: StrategyParams,
): string {
  if (indicator === "ma") {
    if (strategyType === "trend") {
      const p = params as MaTrendParams;
      return `단기(${p.short_period})MA가 장기(${p.long_period})MA를 상향 돌파하면 매수, 하향 돌파하면 매도합니다.`;
    }
    const p = params as MaCounterTrendParams;
    return `가격이 MA(${p.long_period}) 대비 -${p.deviation_pct}% 이하로 벌어지면 매수, +${p.deviation_pct}% 이상 벌어지면 매도합니다.`;
  }

  if (indicator === "rsi") {
    if (strategyType === "trend") {
      const p = params as RsiTrendParams;
      return `RSI(${p.period})가 ${p.threshold}선을 상향 돌파하면 매수, 하향 돌파하면 매도합니다.`;
    }
    const p = params as RsiCounterTrendParams;
    return `RSI(${p.period})가 과매도 기준(${p.oversold}) 이하면 매수, 과매수 기준(${p.overbought}) 이상이면 매도합니다.`;
  }

  if (indicator === "macd") {
    const p = params as MacdParams;
    const label = `MACD(${p.short_period},${p.long_period},${p.signal_period})`;
    return strategyType === "trend"
      ? `${label} 선이 시그널선을 상향 돌파하면 매수, 하향 돌파하면 매도합니다.`
      : `${label} 히스토그램이 저점에서 반등하면 매수, 고점에서 하락 전환하면 매도합니다.`;
  }

  const p = params as BollingerParams;
  const label = `볼린저밴드(${p.period}, ${p.std_multiplier})`;
  return strategyType === "trend"
    ? `가격이 ${label} 상단을 상향 돌파하면 매수, 하단을 하향 돌파하면 매도합니다.`
    : `가격이 ${label} 하단에 닿거나 하회하면 매수, 상단에 닿거나 상회하면 매도합니다.`;
}

export function buildExitText(stopLossPct: string, takeProfitPct: string): string | null {
  const lines: string[] = [];
  if (stopLossPct) {
    lines.push(`진입가 대비 -${stopLossPct}% 도달 시 손절합니다.`);
  }
  if (takeProfitPct) {
    lines.push(`진입가 대비 +${takeProfitPct}% 도달 시 익절합니다.`);
  }
  return lines.length > 0 ? lines.join(" ") : null;
}
