import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { NumberInput } from "../NumberInput";
import type { AvailableBalance } from "../../types/coins";
import type { OrderCreateInput, OrderSide, OrderType } from "../../types/orders";

// 01-erd.md 3.2절 — 체결 수수료율(소수 비율). 비율버튼의 매수 가능 수량 계산에만 쓰인다
// (실제 검증·체결은 항상 백엔드 services/orders.py·matcher.py가 최종 판단한다).
const TRADING_FEE_RATE = 0.0005;
const RATIOS = [10, 25, 50, 75, 100];

interface OrderFormPanelProps {
  symbol: string | null;
  currentPrice: number | null;
  availableBalance: AvailableBalance | null;
  price: string;
  onPriceChange: (price: string) => void;
  onSubmit: (input: OrderCreateInput) => Promise<void>;
  onSuccess: () => void;
  // 07-auto-trading.md 5장 FR-M10 — 활성 자동매매 슬롯이 있는 코인이면 true.
  isLocked?: boolean;
}

function truncate(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.floor(value * factor) / factor;
}

// 03-manual-trading.md 2-D — 매수/매도·지정가/시장가/예약가 탭, 콤마 입력, 비율버튼, 잔고 표시.
// 호가창 옆(.trade-order-row 우측 열)에 배치된다. 내부는 flex-wrap이라 좁은 폭에서는
// 필드가 세로로 쌓인다 (레이아웃 세부는 index.css .trade-order-bar).
export function OrderFormPanel({
  symbol,
  currentPrice,
  availableBalance,
  price,
  onPriceChange,
  onSubmit,
  onSuccess,
  isLocked,
}: OrderFormPanelProps) {
  const [side, setSide] = useState<OrderSide>("buy");
  const [orderType, setOrderType] = useState<OrderType>("limit");
  const [triggerPrice, setTriggerPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setQuantity("");
    setTriggerPrice("");
    setError(undefined);
  }, [symbol, side, orderType]);

  const effectivePrice = orderType === "market" ? currentPrice ?? 0 : Number(price || "0");
  const parsedQuantity = Number(quantity || "0");
  const orderAmount = effectivePrice * parsedQuantity;

  const availableKrw = availableBalance ? Number(availableBalance.available_krw) : 0;
  const availableQuantity = availableBalance ? Number(availableBalance.available_quantity) : 0;

  const handleRatioClick = (ratio: number) => {
    if (side === "buy") {
      if (effectivePrice <= 0) return;
      const budget = (availableKrw * ratio) / 100;
      const qty = budget / (effectivePrice * (1 + TRADING_FEE_RATE));
      setQuantity(String(Math.max(truncate(qty, 8), 0)));
    } else {
      const qty = (availableQuantity * ratio) / 100;
      setQuantity(String(Math.max(truncate(qty, 8), 0)));
    }
  };

  const isSubmitDisabled =
    !symbol ||
    isSubmitting ||
    parsedQuantity <= 0 ||
    (orderType !== "market" && effectivePrice <= 0) ||
    (orderType === "reserved" && Number(triggerPrice || "0") <= 0) ||
    (side === "buy" && orderAmount * (1 + TRADING_FEE_RATE) > availableKrw) ||
    (side === "sell" && parsedQuantity > availableQuantity);

  if (isLocked) {
    return (
      <div className="dashboard-card trade-order-bar">
        <p className="auto-locked-notice">
          자동매매가 실행 중인 코인입니다. 자동매매를 먼저 종료해주세요.
        </p>
      </div>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!symbol || isSubmitDisabled) return;

    setIsSubmitting(true);
    setError(undefined);
    try {
      await onSubmit({
        coin_symbol: symbol,
        side,
        order_type: orderType,
        quantity,
        price: orderType === "market" ? undefined : price,
        trigger_price: orderType === "reserved" ? triggerPrice : undefined,
      });
      setQuantity("");
      setTriggerPrice("");
      onSuccess();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "주문 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="dashboard-card trade-order-bar" onSubmit={handleSubmit}>
      <div className="trade-order-bar-group">
        <div className="trade-order-tab-row">
          <button
            type="button"
            className={side === "buy" ? "trade-order-tab is-buy is-active" : "trade-order-tab is-buy"}
            onClick={() => setSide("buy")}
          >
            매수
          </button>
          <button
            type="button"
            className={side === "sell" ? "trade-order-tab is-sell is-active" : "trade-order-tab is-sell"}
            onClick={() => setSide("sell")}
          >
            매도
          </button>
        </div>
        <div className="dashboard-tab-row">
          <button
            type="button"
            className={orderType === "limit" ? "dashboard-tab is-active" : "dashboard-tab"}
            onClick={() => setOrderType("limit")}
          >
            지정가
          </button>
          <button
            type="button"
            className={orderType === "market" ? "dashboard-tab is-active" : "dashboard-tab"}
            onClick={() => setOrderType("market")}
          >
            시장가
          </button>
          <button
            type="button"
            className={orderType === "reserved" ? "dashboard-tab is-active" : "dashboard-tab"}
            onClick={() => setOrderType("reserved")}
          >
            예약가
          </button>
        </div>
      </div>

      <div className="trade-order-bar-group trade-order-bar-inputs">
        {orderType === "reserved" && (
          <NumberInput
            label="감시가격"
            value={triggerPrice}
            onChange={setTriggerPrice}
            placeholder="감시가격"
            suffix="원"
          />
        )}
        <NumberInput
          label={orderType === "reserved" ? "주문가격" : "가격"}
          value={orderType === "market" ? "" : price}
          onChange={onPriceChange}
          placeholder={orderType === "market" ? "시장가 즉시체결" : "주문 가격"}
          suffix="원"
          disabled={orderType === "market"}
        />
        <NumberInput label="수량" value={quantity} onChange={setQuantity} placeholder="주문 수량" />
      </div>

      <div className="trade-order-bar-group">
        <div className="trade-order-ratio-row">
          {RATIOS.map((ratio) => (
            <button type="button" key={ratio} className="dashboard-chip-button" onClick={() => handleRatioClick(ratio)}>
              {ratio === 100 ? "최대" : `${ratio}%`}
            </button>
          ))}
        </div>
      </div>

      <div className="trade-order-bar-group trade-order-bar-summary">
        <div className="trade-order-amount-row">
          <span className="dashboard-card-label">주문금액</span>
          <span>{Math.round(orderAmount).toLocaleString("ko-KR")}원</span>
        </div>
        <div className="trade-order-balance-row">
          <span>가용 원화 {Math.round(availableKrw).toLocaleString("ko-KR")}원</span>
          <span>가용 수량 {availableQuantity}</span>
        </div>
        {error && <p className="auth-error-message">{error}</p>}
      </div>

      <button
        type="submit"
        className={side === "buy" ? "auth-button trade-submit-button is-buy" : "auth-button trade-submit-button is-sell"}
        disabled={isSubmitDisabled}
      >
        {side === "buy" ? "매수" : "매도"}
      </button>
    </form>
  );
}
