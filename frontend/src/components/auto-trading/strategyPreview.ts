import type {
  BollingerParams,
  DcaParams,
  GridParams,
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
  indicator: Indicator | null,
  params: StrategyParams,
): string {
  if (strategyType === "dca") {
    const p = params as DcaParams;
    const period = { day: "매일", week: "매주", month: "매월" }[p.buy_period] ?? p.buy_period;
    const ending =
      p.end_condition === "count"
        ? `총 ${p.max_count}회까지 매수합니다.`
        : "투자금이 소진될 때까지 매수합니다.";
    const extra = p.extra_buy_enabled
      ? ` 직전 매수가보다 ${p.extra_buy_drop_pct}% 이상 떨어지면 1회 추가로 매수합니다.`
      : "";
    return `${period} ${p.amount_per_buy.toLocaleString("ko-KR")}원씩 나눠 매수하고, ${ending}${extra}`;
  }

  if (strategyType === "grid") {
    const p = params as GridParams;
    // 간격(%)은 상한/하한/격자 수에서 따라 나오는 파생값이라 입력이 아니라 여기서 계산해 보여준다
    // (backend/app/strategy_engine/grid.py 모듈 docstring 참고).
    const step = (p.upper_price - p.lower_price) / p.grid_count;
    const stepPct = p.lower_price > 0 ? (step / p.lower_price) * 100 : 0;
    return (
      `${p.lower_price.toLocaleString("ko-KR")}원~${p.upper_price.toLocaleString("ko-KR")}원을 ` +
      `${p.grid_count}칸(칸당 약 ${step.toLocaleString("ko-KR")}원 · 하한가 대비 ${stepPct.toFixed(2)}%)으로 나눠, ` +
      `가격이 한 칸 내려오면 그 칸을 매수하고 한 칸 오르면 매도합니다.`
    );
  }

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

// 손절·익절은 전략유형별로 의미가 다르다 (06-backtesting.md 2.5절). 그리드는 %기반 손절·익절이
// 없고 "하한가 이탈 손절"만 있으며, 익절은 라인별로 개별 실현된다.
export function buildExitText(
  strategyType: StrategyType,
  stopLossPct: string,
  takeProfitPct: string,
  params: StrategyParams,
): string | null {
  if (strategyType === "grid") {
    const p = params as GridParams;
    return `가격이 하한가(${p.lower_price.toLocaleString("ko-KR")}원) 아래로 떨어지면 보유분을 전량 청산합니다.`;
  }

  // DCA는 손절이 없고 "목표 수익률 익절"만 있다 — 도달하면 전량 매도 후 전략을 종료한다.
  if (strategyType === "dca") {
    return takeProfitPct
      ? `평균매수가 대비 +${takeProfitPct}% 도달 시 전량 매도하고 자동매매를 종료합니다.`
      : null;
  }

  const lines: string[] = [];
  if (stopLossPct) {
    lines.push(`진입가 대비 -${stopLossPct}% 도달 시 손절합니다.`);
  }
  if (takeProfitPct) {
    lines.push(`진입가 대비 +${takeProfitPct}% 도달 시 익절합니다.`);
  }
  return lines.length > 0 ? lines.join(" ") : null;
}
