import type { PriceTick } from "../../types/dashboard";
import type { Coin } from "../../types/coins";

interface PriceHeaderPanelProps {
  coin: Coin | null;
  tick: PriceTick | null;
}

// 03-manual-trading.md 2-B — 현재가 대형 텍스트 + 고가/저가/24H 거래량 정보줄
export function PriceHeaderPanel({ coin, tick }: PriceHeaderPanelProps) {
  if (!coin) {
    return <div className="dashboard-card">코인을 선택해주세요.</div>;
  }

  const changeRate = tick ? tick.signed_change_rate * 100 : 0;
  const changeClass =
    tick?.change === "RISE" ? "is-positive" : tick?.change === "FALL" ? "is-negative" : "";

  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">
        {coin.korean_name} ({coin.symbol})
      </p>
      <p className={`trade-price-large ${changeClass}`}>
        {tick ? Math.round(tick.trade_price).toLocaleString("ko-KR") : "-"}
      </p>
      <p className={`dashboard-profit-pct ${changeClass}`}>
        {tick ? `${changeRate > 0 ? "+" : ""}${changeRate.toFixed(2)}%` : "-"}
      </p>
      <div className="trade-price-info-row">
        <span>고가 {tick ? Math.round(tick.high_price).toLocaleString("ko-KR") : "-"}</span>
        <span>저가 {tick ? Math.round(tick.low_price).toLocaleString("ko-KR") : "-"}</span>
        <span>
          24H 거래량 {tick ? tick.acc_trade_volume_24h.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : "-"}
        </span>
      </div>
    </div>
  );
}
