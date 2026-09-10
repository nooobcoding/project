import type { Coin } from "../../types/coins";
import type { SlotSignal, StrategySlot } from "../../types/strategySlots";

interface SignalMonitorPanelProps {
  slots: StrategySlot[];
  coins: Coin[];
  signals: Record<number, SlotSignal>;
}

const STRATEGY_TYPE_LABEL: Record<string, string> = {
  trend: "추세추종",
  counter_trend: "역추세",
  grid: "그리드",
};

const INDICATOR_LABEL: Record<string, string> = {
  ma: "MA",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "볼린저",
};

const INTERVAL_LABEL: Record<string, string> = {
  "1m": "1분봉",
  "10m": "10분봉",
  "30m": "30분봉",
  "1h": "1시간봉",
  "1d": "일봉",
};

function statusLabel(signal: SlotSignal | undefined): { text: string; className: string } {
  if (!signal) return { text: "조회 중", className: "" };
  if (signal.signal === "buy") return { text: "매수 신호", className: "is-positive" };
  if (signal.signal === "sell") return { text: "매도 신호", className: "is-negative" };
  return { text: "신호 없음", className: "" };
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

// 07-auto-trading.md 3-B "신호 모니터링" — 활성 슬롯마다 1장씩. 백엔드
// GET /api/strategy-slots/{id}/signals는 buy/sell/None 스냅샷만 돌려주므로(RSI 수치 같은
// 원자료는 반환하지 않음), 카드는 "지금 판정이 매수/매도/없음"까지만 보여준다 — 지표 원자값
// 표시는 별도 응답 스키마 확장이 필요해 이번 스텝 범위 밖으로 남긴다.
export function SignalMonitorPanel({ slots, coins, signals }: SignalMonitorPanelProps) {
  const activeSlots = slots.filter((slot) => slot.is_active);

  return (
    <div className="dashboard-card">
      <p className="dashboard-card-label">신호 모니터링</p>
      {activeSlots.length === 0 ? (
        <p className="dashboard-empty-text">실행 중인 전략이 없습니다.</p>
      ) : (
        <div className="auto-signal-grid">
          {activeSlots.map((slot) => {
            const coin = coins.find((c) => c.symbol === slot.coin_symbol);
            const signal = signals[slot.id];
            const status = statusLabel(signal);
            const interval = (slot.params as { interval?: string }).interval;
            return (
              <div key={slot.id} className="auto-signal-card">
                <div className="auto-signal-card-header">
                  <span>{coin?.korean_name ?? slot.coin_symbol}</span>
                  <span className={`auto-signal-status ${status.className}`}>{status.text}</span>
                </div>
                <div className="auto-signal-card-meta">
                  <span>{STRATEGY_TYPE_LABEL[slot.strategy_type]}</span>
                  {slot.indicator && <span>{INDICATOR_LABEL[slot.indicator]}</span>}
                  {interval && <span>{INTERVAL_LABEL[interval] ?? interval}</span>}
                </div>
                {signal && (
                  <p className="auto-signal-card-time">{formatTime(signal.evaluated_at)} 기준</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
