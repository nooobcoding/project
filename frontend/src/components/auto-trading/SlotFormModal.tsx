import { useMemo, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { NumberInput } from "../NumberInput";
import { ToggleSwitch } from "../ToggleSwitch";
import type { CandleInterval } from "../../types/candles";
import type { Coin } from "../../types/coins";
import type {
  DcaEndCondition,
  DcaPeriod,
  Indicator,
  StrategyParams,
  StrategySlot,
  StrategySlotWriteInput,
  StrategyType,
} from "../../types/strategySlots";
import { CoinSearchList } from "./CoinSearchList";
import { buildConditionText, buildExitText } from "./strategyPreview";

interface SlotFormModalProps {
  coins: Coin[];
  slot: StrategySlot | null; // null이면 생성, 값이 있으면 그 슬롯을 수정
  onClose: () => void;
  onCreate: (input: StrategySlotWriteInput) => Promise<void>;
  onUpdate: (slotId: number, input: StrategySlotWriteInput) => Promise<void>;
}

const STRATEGY_TYPE_LABEL: Record<StrategyType, string> = {
  trend: "추세추종",
  counter_trend: "역추세",
  grid: "그리드",
  dca: "DCA",
};

const DCA_PERIOD_LABEL: Record<string, string> = {
  day: "매일",
  week: "매주",
  month: "매월",
};

const INDICATOR_LABEL: Record<Indicator, string> = {
  ma: "MA(이동평균)",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "볼린저밴드",
};

const INTERVAL_LABEL: Record<string, string> = {
  "1m": "1분봉",
  "10m": "10분봉",
  "30m": "30분봉",
  "1h": "1시간봉",
  "1d": "일봉",
};

// 06-backtesting.md 2.2절 기본값. MA·그리드 가격대는 정해진 기본값이 없는 필수 입력이라
// 빈 문자열로 둔다.
function defaultParamValues() {
  return {
    interval: "1d",
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
    buy_period: "week",
    amount_per_buy: "",
    end_condition: "count",
    max_count: "10",
    extra_buy_enabled: "false",
    extra_buy_drop_pct: "5",
  };
}

function paramsToFormValues(params: StrategyParams | undefined): ReturnType<typeof defaultParamValues> {
  const base = defaultParamValues();
  if (!params) return base;
  const record = params as unknown as Record<string, string | number>;
  const merged = { ...base };
  for (const key of Object.keys(base) as (keyof typeof base)[]) {
    if (record[key] !== undefined) {
      merged[key] = String(record[key]);
    }
  }
  return merged;
}

// 07-auto-trading.md 3-A "전략 유형/지표 선택, 파라미터 폼, 손절·익절 — 06-backtesting.md
// 2.1~2.5절 그대로 적용". 슬롯 하나의 생성·수정을 모두 담당하는 모달. 활성(ON) 상태인 슬롯은
// 백엔드가 수정을 막으므로(services/strategy_slots.py update_slot — 워커가 이미 이 설정으로
// state를 쌓고 있는 도중 값이 바뀌면 그 상태의 의미가 깨진다) 여기서도 미리 막아 보여준다.
export function SlotFormModal({ coins, slot, onClose, onCreate, onUpdate }: SlotFormModalProps) {
  const isEdit = slot !== null;
  const isLockedForEdit = isEdit && slot.is_active;

  const [coinSymbol, setCoinSymbol] = useState(slot?.coin_symbol ?? coins[0]?.symbol ?? "");
  const [strategyType, setStrategyType] = useState<StrategyType>(slot?.strategy_type ?? "trend");
  const [indicator, setIndicator] = useState<Indicator>(slot?.indicator ?? "ma");
  const [paramValues, setParamValues] = useState(() => paramsToFormValues(slot?.params));
  const [investAmount, setInvestAmount] = useState(slot?.invest_amount ?? "");
  const [stopLossPct, setStopLossPct] = useState(slot?.stop_loss_pct ?? "");
  const [takeProfitPct, setTakeProfitPct] = useState(slot?.take_profit_pct ?? "");
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const setParam = (key: keyof ReturnType<typeof defaultParamValues>) => (value: string) =>
    setParamValues((prev) => ({ ...prev, [key]: value }));

  const isGrid = strategyType === "grid";
  const isDca = strategyType === "dca";
  // 지표를 쓰지 않는 전략유형 (06-backtesting.md 2.3·2.4절)
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
    return true; // RSI/MACD/볼린저는 06 문서 기본값이 있어 항상 채워져 있다.
  }, [isGrid, isDca, indicator, strategyType, paramValues]);

  const isSubmitDisabled =
    isLockedForEdit ||
    isSubmitting ||
    !coinSymbol ||
    !requiredParamsFilled ||
    !investAmount ||
    Number(investAmount) <= 0;

  const buildParams = (): StrategyParams => {
    const p = paramValues;
    const interval = p.interval as CandleInterval;
    if (isDca) {
      return {
        interval,
        buy_period: p.buy_period as DcaPeriod,
        amount_per_buy: Number(p.amount_per_buy || 0),
        end_condition: p.end_condition as DcaEndCondition,
        max_count: Number(p.max_count || 10),
        extra_buy_enabled: p.extra_buy_enabled === "true",
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
    return {
      interval,
      period: Number(p.period || 20),
      std_multiplier: Number(p.std_multiplier),
    };
  };

  const previewText = buildConditionText(strategyType, hasNoIndicator ? null : indicator, buildParams());
  const exitText = buildExitText(strategyType, stopLossPct, takeProfitPct, buildParams());

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitDisabled) return;

    setIsSubmitting(true);
    setError(undefined);
    const input: StrategySlotWriteInput = {
      coin_symbol: coinSymbol,
      strategy_type: strategyType,
      // 그리드·DCA는 지표를 쓰지 않는다 — 백엔드도 (전략유형, None) 조합만 받는다.
      indicator: hasNoIndicator ? null : indicator,
      params: buildParams(),
      invest_amount: investAmount,
      // 손절·익절은 전략유형별로 의미가 다르다 (06-backtesting.md 2.5절).
      // 그리드: 하한가 이탈 손절 + 라인별 실현이라 둘 다 없음 / DCA: 손절 없고 목표 수익률 익절만.
      stop_loss_pct: isGrid || isDca ? undefined : stopLossPct || undefined,
      take_profit_pct: isGrid ? undefined : takeProfitPct || undefined,
    };
    try {
      if (isEdit) {
        await onUpdate(slot.id, input);
      } else {
        await onCreate(input);
      }
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "저장 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="dashboard-modal-backdrop" onClick={onClose}>
      <div className="dashboard-modal auto-slot-modal" onClick={(event) => event.stopPropagation()}>
        <h3>{isEdit ? "전략 수정" : "전략 추가"}</h3>

        {isLockedForEdit && (
          <p className="auto-locked-notice">실행 중인 전략은 먼저 OFF한 뒤 수정할 수 있습니다.</p>
        )}

        <form className="auto-slot-form" onSubmit={handleSubmit}>
          <div className="settings-field">
            <label className="settings-field-label">대상 코인</label>
            <CoinSearchList
              coins={coins}
              selectedSymbol={coinSymbol}
              onSelect={setCoinSymbol}
              disabled={isLockedForEdit}
            />
          </div>

          <div className="dashboard-tab-row">
            {(Object.keys(STRATEGY_TYPE_LABEL) as StrategyType[]).map((type) => (
              <button
                key={type}
                type="button"
                className={strategyType === type ? "dashboard-tab is-active" : "dashboard-tab"}
                onClick={() => setStrategyType(type)}
                disabled={isLockedForEdit}
              >
                {STRATEGY_TYPE_LABEL[type]}
              </button>
            ))}
          </div>

          {/* 그리드·DCA는 지표를 쓰지 않는다 (06-backtesting.md 2.3·2.4절) */}
          {!hasNoIndicator && (
            <div className="dashboard-tab-row">
              {(Object.keys(INDICATOR_LABEL) as Indicator[]).map((ind) => (
                <button
                  key={ind}
                  type="button"
                  className={indicator === ind ? "dashboard-tab is-active" : "dashboard-tab"}
                  onClick={() => setIndicator(ind)}
                  disabled={isLockedForEdit}
                >
                  {INDICATOR_LABEL[ind]}
                </button>
              ))}
            </div>
          )}

          <div className="settings-field">
            <label className="settings-field-label">봉단위</label>
            <select
              className="auth-input"
              value={paramValues.interval}
              onChange={(event) => setParam("interval")(event.target.value)}
              disabled={isLockedForEdit}
            >
              {Object.entries(INTERVAL_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>

          {isDca && (
            <>
              <div className="settings-field">
                <label className="settings-field-label">매수 주기</label>
                <select
                  className="auth-input"
                  value={paramValues.buy_period}
                  onChange={(event) => setParam("buy_period")(event.target.value)}
                  disabled={isLockedForEdit}
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
                  onChange={(event) => setParam("end_condition")(event.target.value)}
                  disabled={isLockedForEdit}
                >
                  <option value="count">총 횟수만큼 매수</option>
                  <option value="budget">투자금이 소진될 때까지</option>
                </select>
              </div>
              <div className="settings-toggle-row">
                <span className="settings-toggle-label">추가 매수 (하락 시 1회 더)</span>
                <ToggleSwitch
                  checked={paramValues.extra_buy_enabled === "true"}
                  onChange={(value) => setParam("extra_buy_enabled")(String(value))}
                  disabled={isLockedForEdit}
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
                  disabled={isLockedForEdit}
                />
                {paramValues.end_condition === "count" && (
                  <NumberInput
                    label="총 횟수"
                    value={paramValues.max_count}
                    onChange={setParam("max_count")}
                    suffix="회"
                    disabled={isLockedForEdit}
                  />
                )}
                {paramValues.extra_buy_enabled === "true" && (
                  <NumberInput
                    label="추가매수 하락폭"
                    value={paramValues.extra_buy_drop_pct}
                    onChange={setParam("extra_buy_drop_pct")}
                    suffix="%"
                    disabled={isLockedForEdit}
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
                  disabled={isLockedForEdit}
                />
                <NumberInput
                  label="상한가"
                  value={paramValues.upper_price}
                  onChange={setParam("upper_price")}
                  suffix="원"
                  disabled={isLockedForEdit}
                />
                <NumberInput
                  label="격자 수"
                  value={paramValues.grid_count}
                  onChange={setParam("grid_count")}
                  disabled={isLockedForEdit}
                />
              </>
            )}

            {!hasNoIndicator && indicator === "ma" && (
              <>
                <NumberInput
                  label="단기 기간"
                  value={paramValues.short_period}
                  onChange={setParam("short_period")}
                  disabled={isLockedForEdit}
                />
                <NumberInput
                  label="장기 기간"
                  value={paramValues.long_period}
                  onChange={setParam("long_period")}
                  disabled={isLockedForEdit}
                />
                {strategyType === "counter_trend" && (
                  <NumberInput
                    label="이격도 기준"
                    value={paramValues.deviation_pct}
                    onChange={setParam("deviation_pct")}
                    suffix="%"
                    disabled={isLockedForEdit}
                  />
                )}
              </>
            )}

            {!hasNoIndicator && indicator === "rsi" && (
              <>
                <NumberInput
                  label="RSI 기간"
                  value={paramValues.period}
                  onChange={setParam("period")}
                  disabled={isLockedForEdit}
                />
                {strategyType === "trend" ? (
                  <NumberInput
                    label="기준선"
                    value={paramValues.threshold}
                    onChange={setParam("threshold")}
                    disabled={isLockedForEdit}
                  />
                ) : (
                  <>
                    <NumberInput
                      label="과매도 기준"
                      value={paramValues.oversold}
                      onChange={setParam("oversold")}
                      disabled={isLockedForEdit}
                    />
                    <NumberInput
                      label="과매수 기준"
                      value={paramValues.overbought}
                      onChange={setParam("overbought")}
                      disabled={isLockedForEdit}
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
                  disabled={isLockedForEdit}
                />
                <NumberInput
                  label="장기 EMA"
                  value={paramValues.long_period || "26"}
                  onChange={setParam("long_period")}
                  disabled={isLockedForEdit}
                />
                <NumberInput
                  label="시그널"
                  value={paramValues.signal_period}
                  onChange={setParam("signal_period")}
                  disabled={isLockedForEdit}
                />
              </>
            )}

            {!hasNoIndicator && indicator === "bollinger" && (
              <>
                <NumberInput
                  label="기간"
                  value={paramValues.period || "20"}
                  onChange={setParam("period")}
                  disabled={isLockedForEdit}
                />
                <NumberInput
                  label="표준편차 승수"
                  value={paramValues.std_multiplier}
                  onChange={setParam("std_multiplier")}
                  disabled={isLockedForEdit}
                />
              </>
            )}
          </div>

          <NumberInput
            label="투자금"
            value={investAmount}
            onChange={setInvestAmount}
            suffix="원"
            disabled={isLockedForEdit}
          />

          {/* 손절·익절은 전략유형별로 의미가 다르다 (06-backtesting.md 2.5절).
              그리드: 하한가 이탈로 손절하고 익절은 라인별 실현이라 %입력이 아예 없다.
              DCA: 손절이 없고 "목표 수익률 익절"만 있다. */}
          {!isGrid && (
            <div className="auto-param-grid">
              {!isDca && (
                <NumberInput
                  label="손절 (선택)"
                  value={stopLossPct}
                  onChange={setStopLossPct}
                  suffix="%"
                  disabled={isLockedForEdit}
                />
              )}
              <NumberInput
                label={isDca ? "목표 수익률 익절 (선택)" : "익절 (선택)"}
                value={takeProfitPct}
                onChange={setTakeProfitPct}
                suffix="%"
                disabled={isLockedForEdit}
              />
            </div>
          )}

          <div className="auto-preview-box">
            <p className="dashboard-card-label">전략 미리보기</p>
            <p>{previewText}</p>
            {exitText && <p>{exitText}</p>}
          </div>

          {error && <p className="auth-error-message">{error}</p>}

          <div className="dashboard-modal-actions">
            <button type="button" className="dashboard-chip-button" onClick={onClose}>
              취소
            </button>
            <button type="submit" className="auth-button" disabled={isSubmitDisabled}>
              저장
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
