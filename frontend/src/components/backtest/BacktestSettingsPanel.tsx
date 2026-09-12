import { useEffect, useMemo, useState, type FormEvent } from "react";
import { CoinSearchList } from "../auto-trading/CoinSearchList";
import { buildConditionText, buildExitText } from "../auto-trading/strategyPreview";
import { NumberInput } from "../NumberInput";
import { ToggleSwitch } from "../ToggleSwitch";
import type { CandleInterval } from "../../types/candles";
import type { Coin } from "../../types/coins";
import type {
  DcaEndCondition,
  DcaPeriod,
  Indicator,
  StrategyParams,
  StrategyType,
} from "../../types/strategySlots";
import type { BacktestRunInput } from "../../types/backtest";
import {
  INDICATOR_LABEL,
  INTERVAL_LABEL,
  MAX_RANGE_DAYS,
  STRATEGY_TYPE_LABEL,
  addDays,
  earlierDate,
  exceedsRangeLimit,
  rangeLimitErrorText,
  subtractDays,
  todayDateInput,
} from "./backtestConstants";

interface BacktestSettingsPanelProps {
  coins: Coin[];
  onRun: (input: BacktestRunInput) => void;
  isRunning: boolean;
  /** 불러오기 팝업에서 저장된 설정을 눌렀을 때만 채워진다 — 없으면 06 문서 기본값(일봉·최근
   * 1년·BTC·추세추종·MA)으로 시작한다. */
  initialConfig?: BacktestRunInput;
}

const DCA_PERIOD_LABEL: Record<DcaPeriod, string> = { day: "매일", week: "매주", month: "매월" };

// SlotFormModal.defaultParamValues와 같은 목록·기본값이다 — 06-backtesting.md 2.2절 기본값을
// 그대로 쓴다. 단일 flat 문자열 dict로 모든 지표 파라미터를 담는 것도 동일한 이유(조합마다
// 필요한 키만 골라 쓰고 나머지는 버림)에서다.
function defaultParamValues() {
  return {
    short_period: "",
    long_period: "",
    deviation_pct: "5",
    period: "14",
    threshold: "50",
    oversold: "30",
    overbought: "70",
    signal_period: "9",
    std_multiplier: "2.0",
    lower_price: "",
    upper_price: "",
    grid_count: "5",
    buy_period: "week" as DcaPeriod,
    amount_per_buy: "",
    end_condition: "count" as DcaEndCondition,
    max_count: "10",
    extra_buy_enabled: false,
    extra_buy_drop_pct: "5",
  };
}

type ParamValues = ReturnType<typeof defaultParamValues>;

function paramsFromConfig(params: StrategyParams | undefined): ParamValues {
  const base = defaultParamValues();
  if (!params) return base;
  const record = params as unknown as Record<string, string | number | boolean>;
  const merged = { ...base };
  for (const key of Object.keys(base) as (keyof ParamValues)[]) {
    if (record[key] === undefined) continue;
    (merged as Record<string, unknown>)[key] =
      typeof base[key] === "string" ? String(record[key]) : record[key];
  }
  return merged;
}

// SCR-05 설정 패널 (06-backtesting.md 3-A절). SlotFormModal의 3단계 동적 폼 로직(전략유형→
// 지표→파라미터)을 거의 그대로 옮기되, "저장"이 아니라 "실행"으로 끝나고 슬롯 활성화 잠금
// (isLockedForEdit) 개념이 없다 — 백테스팅은 반복 실행이 전제라 항상 값을 바꿀 수 있어야 한다.
export function BacktestSettingsPanel({
  coins,
  onRun,
  isRunning,
  initialConfig,
}: BacktestSettingsPanelProps) {
  const [coinSymbol, setCoinSymbol] = useState(
    initialConfig?.coin_symbol ?? coins.find((coin) => coin.symbol === "BTC")?.symbol ?? coins[0]?.symbol ?? "",
  );
  const [strategyType, setStrategyType] = useState<StrategyType>(initialConfig?.strategy_type ?? "trend");
  const [indicator, setIndicator] = useState<Indicator>(initialConfig?.indicator ?? "ma");
  const [interval, setInterval] = useState<CandleInterval>(
    ((initialConfig?.params as { interval?: CandleInterval } | undefined)?.interval as CandleInterval) ??
      "1d",
  );
  const [paramValues, setParamValues] = useState<ParamValues>(() =>
    paramsFromConfig(initialConfig?.params),
  );
  // 기본값: 일봉·최근 1년 (06-backtesting.md 2.1-1절).
  const [endDate, setEndDate] = useState(initialConfig?.end_date ?? todayDateInput());
  const [startDate, setStartDate] = useState(
    initialConfig?.start_date ?? subtractDays(todayDateInput(), 364),
  );
  const [initialCapital, setInitialCapital] = useState(initialConfig?.initial_capital ?? "10000000");
  const [feeRate, setFeeRate] = useState(initialConfig?.fee_rate ?? "0.05");
  const [slippageRate, setSlippageRate] = useState(initialConfig?.slippage_rate ?? "0.1");
  const [stopLossPct, setStopLossPct] = useState(initialConfig?.stop_loss_pct ?? "");
  const [takeProfitPct, setTakeProfitPct] = useState(initialConfig?.take_profit_pct ?? "");

  // 코인 목록이 나중에 도착하는 첫 렌더(초기값이 빈 문자열)를 보정한다 — 불러온 설정이 없을 때만.
  useEffect(() => {
    if (!initialConfig && !coinSymbol && coins.length > 0) {
      setCoinSymbol(coins.find((coin) => coin.symbol === "BTC")?.symbol ?? coins[0].symbol);
    }
  }, [coins, coinSymbol, initialConfig]);

  // 봉단위를 바꿔 지금 기간이 새 상한을 넘기면 시작일을 그 상한에 맞춰 당긴다
  // (06-backtesting.md 2.1-1절 "선택 가능 범위를 동적으로 좁힌다").
  useEffect(() => {
    if (exceedsRangeLimit(interval, startDate, endDate)) {
      setStartDate(subtractDays(endDate, MAX_RANGE_DAYS[interval] - 1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interval]);

  const setParam = <K extends keyof ParamValues>(key: K) => (value: ParamValues[K]) =>
    setParamValues((prev) => ({ ...prev, [key]: value }));

  const isGrid = strategyType === "grid";
  const isDca = strategyType === "dca";
  const hasNoIndicator = isGrid || isDca;

  const requiredParamsFilled = useMemo(() => {
    if (isDca) {
      return paramValues.amount_per_buy !== "" && Number(paramValues.amount_per_buy) > 0;
    }
    if (isGrid) {
      return (
        paramValues.lower_price !== "" &&
        paramValues.upper_price !== "" &&
        Number(paramValues.upper_price) > Number(paramValues.lower_price) &&
        Number(paramValues.grid_count) >= 2
      );
    }
    if (indicator === "ma") {
      const base = paramValues.short_period !== "" && paramValues.long_period !== "";
      return strategyType === "counter_trend" ? base && paramValues.deviation_pct !== "" : base;
    }
    return true; // RSI/MACD/볼린저는 기본값이 있어 항상 채워져 있다.
  }, [isGrid, isDca, indicator, strategyType, paramValues]);

  const dateRangeError = endDate < startDate ? "종료일은 시작일 이후로 설정해주세요." : null;
  const rangeLimitError =
    !dateRangeError && exceedsRangeLimit(interval, startDate, endDate)
      ? rangeLimitErrorText(interval)
      : null;
  const dateError = dateRangeError ?? rangeLimitError;

  // 봉단위별 최대 조회 기간(MAX_RANGE_DAYS)을 벗어나는 날짜는 달력에서 아예 고를 수 없게
  // <input type="date">의 min/max로 막는다 — dateError 문구는 그 방어를 뚫는 경우(예:
  // 이 기간을 골라둔 채로 봉단위를 더 좁은 쪽으로 바꾼 직후, 위 useEffect가 보정하기 전 한
  // 프레임)를 위한 안전망으로 남긴다.
  const startDateMin = subtractDays(endDate, MAX_RANGE_DAYS[interval] - 1);
  const endDateMax = earlierDate(todayDateInput(), addDays(startDate, MAX_RANGE_DAYS[interval] - 1));

  const isRunDisabled =
    isRunning ||
    !coinSymbol ||
    !requiredParamsFilled ||
    !initialCapital ||
    Number(initialCapital) <= 0 ||
    !!dateError;

  const buildParams = (): StrategyParams => {
    const p = paramValues;
    if (isDca) {
      return {
        interval,
        buy_period: p.buy_period,
        amount_per_buy: Number(p.amount_per_buy || 0),
        end_condition: p.end_condition,
        max_count: Number(p.max_count || 10),
        extra_buy_enabled: p.extra_buy_enabled,
        extra_buy_drop_pct: Number(p.extra_buy_drop_pct || 5),
      };
    }
    if (isGrid) {
      return {
        interval,
        lower_price: Number(p.lower_price || 0),
        upper_price: Number(p.upper_price || 0),
        grid_count: Number(p.grid_count || 5),
      };
    }
    if (indicator === "ma") {
      return strategyType === "trend"
        ? { interval, short_period: Number(p.short_period), long_period: Number(p.long_period) }
        : {
            interval,
            short_period: Number(p.short_period),
            long_period: Number(p.long_period),
            deviation_pct: Number(p.deviation_pct),
          };
    }
    if (indicator === "rsi") {
      return strategyType === "trend"
        ? { interval, period: Number(p.period), threshold: Number(p.threshold) }
        : {
            interval,
            period: Number(p.period),
            oversold: Number(p.oversold),
            overbought: Number(p.overbought),
          };
    }
    if (indicator === "macd") {
      return {
        interval,
        short_period: Number(p.short_period || 12),
        long_period: Number(p.long_period || 26),
        signal_period: Number(p.signal_period),
      };
    }
    return { interval, period: Number(p.period || 20), std_multiplier: Number(p.std_multiplier) };
  };

  const previewText = buildConditionText(strategyType, hasNoIndicator ? null : indicator, buildParams());
  const exitText = buildExitText(strategyType, stopLossPct, takeProfitPct, buildParams());

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isRunDisabled) return;
    onRun({
      coin_symbol: coinSymbol,
      strategy_type: strategyType,
      indicator: hasNoIndicator ? null : indicator,
      params: buildParams(),
      start_date: startDate,
      end_date: endDate,
      initial_capital: initialCapital,
      fee_rate: feeRate,
      slippage_rate: slippageRate,
      // 06-backtesting.md 2.5절 — 그리드는 하한가 이탈 손절만, DCA는 목표수익률 익절만 있다.
      stop_loss_pct: isGrid || isDca ? undefined : stopLossPct || undefined,
      take_profit_pct: isGrid ? undefined : takeProfitPct || undefined,
    });
  };

  return (
    <section className="backtest-panel backtest-settings-panel">
      <form className="backtest-settings-form" onSubmit={handleSubmit}>
        <div className="settings-field">
          <label className="settings-field-label">봉단위</label>
          <select
            className="auth-input"
            value={interval}
            onChange={(event) => setInterval(event.target.value as CandleInterval)}
          >
            {Object.entries(INTERVAL_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="settings-field">
          <label className="settings-field-label">기간</label>
          <div className="backtest-date-range-row">
            <input
              type="date"
              className="wallet-date-input"
              value={startDate}
              min={startDateMin}
              max={endDate}
              onChange={(event) => setStartDate(event.target.value)}
            />
            <span>~</span>
            <input
              type="date"
              className="wallet-date-input"
              value={endDate}
              min={startDate}
              max={endDateMax}
              onChange={(event) => setEndDate(event.target.value)}
            />
          </div>
          {dateError && <p className="auth-error-message">{dateError}</p>}
        </div>

        <div className="settings-field">
          <label className="settings-field-label">대상 코인</label>
          <CoinSearchList coins={coins} selectedSymbol={coinSymbol} onSelect={setCoinSymbol} />
        </div>

        <div className="dashboard-tab-row">
          {(Object.keys(STRATEGY_TYPE_LABEL) as StrategyType[]).map((type) => (
            <button
              key={type}
              type="button"
              className={strategyType === type ? "dashboard-tab is-active" : "dashboard-tab"}
              onClick={() => setStrategyType(type)}
            >
              {STRATEGY_TYPE_LABEL[type]}
            </button>
          ))}
        </div>

        {!hasNoIndicator && (
          <div className="dashboard-tab-row">
            {(Object.keys(INDICATOR_LABEL) as Indicator[]).map((ind) => (
              <button
                key={ind}
                type="button"
                className={indicator === ind ? "dashboard-tab is-active" : "dashboard-tab"}
                onClick={() => setIndicator(ind)}
              >
                {INDICATOR_LABEL[ind]}
              </button>
            ))}
          </div>
        )}

        {isDca && (
          <>
            <div className="settings-field">
              <label className="settings-field-label">매수 주기</label>
              <select
                className="auth-input"
                value={paramValues.buy_period}
                onChange={(event) => setParam("buy_period")(event.target.value as DcaPeriod)}
              >
                {Object.entries(DCA_PERIOD_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div className="settings-field">
              <label className="settings-field-label">종료 조건</label>
              <select
                className="auth-input"
                value={paramValues.end_condition}
                onChange={(event) => setParam("end_condition")(event.target.value as DcaEndCondition)}
              >
                <option value="count">총 횟수만큼 매수</option>
                <option value="budget">투자금이 소진될 때까지</option>
              </select>
            </div>
            <div className="settings-toggle-row">
              <span className="settings-toggle-label">추가 매수 (하락 시 1회 더)</span>
              <ToggleSwitch
                checked={paramValues.extra_buy_enabled}
                onChange={setParam("extra_buy_enabled")}
                label="추가 매수 사용"
              />
            </div>
          </>
        )}

        <div className="auto-param-grid">
          {isDca && (
            <>
              <NumberInput
                label="회당 매수금액"
                value={paramValues.amount_per_buy}
                onChange={setParam("amount_per_buy")}
                suffix="원"
              />
              {paramValues.end_condition === "count" && (
                <NumberInput
                  label="총 횟수"
                  value={paramValues.max_count}
                  onChange={setParam("max_count")}
                  suffix="회"
                />
              )}
              {paramValues.extra_buy_enabled && (
                <NumberInput
                  label="추가매수 하락폭"
                  value={paramValues.extra_buy_drop_pct}
                  onChange={setParam("extra_buy_drop_pct")}
                  suffix="%"
                />
              )}
            </>
          )}

          {isGrid && (
            <>
              <NumberInput
                label="하한가"
                value={paramValues.lower_price}
                onChange={setParam("lower_price")}
                suffix="원"
              />
              <NumberInput
                label="상한가"
                value={paramValues.upper_price}
                onChange={setParam("upper_price")}
                suffix="원"
              />
              <NumberInput label="격자 수" value={paramValues.grid_count} onChange={setParam("grid_count")} />
            </>
          )}

          {!hasNoIndicator && indicator === "ma" && (
            <>
              <NumberInput
                label="단기 기간"
                value={paramValues.short_period}
                onChange={setParam("short_period")}
              />
              <NumberInput
                label="장기 기간"
                value={paramValues.long_period}
                onChange={setParam("long_period")}
              />
              {strategyType === "counter_trend" && (
                <NumberInput
                  label="이격도 기준"
                  value={paramValues.deviation_pct}
                  onChange={setParam("deviation_pct")}
                  suffix="%"
                />
              )}
            </>
          )}

          {!hasNoIndicator && indicator === "rsi" && (
            <>
              <NumberInput label="RSI 기간" value={paramValues.period} onChange={setParam("period")} />
              {strategyType === "trend" ? (
                <NumberInput label="기준선" value={paramValues.threshold} onChange={setParam("threshold")} />
              ) : (
                <>
                  <NumberInput
                    label="과매도 기준"
                    value={paramValues.oversold}
                    onChange={setParam("oversold")}
                  />
                  <NumberInput
                    label="과매수 기준"
                    value={paramValues.overbought}
                    onChange={setParam("overbought")}
                  />
                </>
              )}
            </>
          )}

          {!hasNoIndicator && indicator === "macd" && (
            <>
              <NumberInput
                label="단기 EMA"
                value={paramValues.short_period || "12"}
                onChange={setParam("short_period")}
              />
              <NumberInput
                label="장기 EMA"
                value={paramValues.long_period || "26"}
                onChange={setParam("long_period")}
              />
              <NumberInput
                label="시그널"
                value={paramValues.signal_period}
                onChange={setParam("signal_period")}
              />
            </>
          )}

          {!hasNoIndicator && indicator === "bollinger" && (
            <>
              <NumberInput label="기간" value={paramValues.period || "20"} onChange={setParam("period")} />
              <NumberInput
                label="표준편차 승수"
                value={paramValues.std_multiplier}
                onChange={setParam("std_multiplier")}
              />
            </>
          )}
        </div>

        <NumberInput
          label="초기 투자금"
          value={initialCapital}
          onChange={setInitialCapital}
          suffix="원"
        />
        <div className="auto-param-grid">
          <NumberInput label="수수료율" value={feeRate} onChange={setFeeRate} suffix="%" />
          <NumberInput label="슬리피지율" value={slippageRate} onChange={setSlippageRate} suffix="%" />
        </div>

        {!isGrid && (
          <div className="auto-param-grid">
            {!isDca && (
              <NumberInput
                label="손절 (선택)"
                value={stopLossPct}
                onChange={setStopLossPct}
                suffix="%"
              />
            )}
            <NumberInput
              label={isDca ? "목표 수익률 익절 (선택)" : "익절 (선택)"}
              value={takeProfitPct}
              onChange={setTakeProfitPct}
              suffix="%"
            />
          </div>
        )}

        <div className="auto-preview-box">
          <p className="dashboard-card-label">전략 미리보기</p>
          <p>{previewText}</p>
          {exitText && <p>{exitText}</p>}
        </div>

        <button type="submit" className="auth-button" disabled={isRunDisabled}>
          {isRunning ? "실행 중..." : "실행"}
        </button>
      </form>
    </section>
  );
}
