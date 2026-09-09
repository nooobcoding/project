import { Link } from "react-router-dom";
import type { Coin } from "../../types/coins";
import type { StrategySlot } from "../../types/strategySlots";

interface AutoTradingStatusCardProps {
  slots: StrategySlot[];
  coins: Coin[];
}

const STRATEGY_TYPE_LABEL: Record<string, string> = {
  trend: "추세추종",
  counter_trend: "역추세",
};

// 02-dashboard.md 2-B — 07-auto-trading 완료 후 실제 슬롯 데이터에 연결.
// 워커는 브라우저 세션과 무관하게 서버에서 상시 도므로(07-auto-trading.md 4장), 이 카드는
// 상태를 조작하지 않고 요약만 보여주며 자세한 조작은 /auto로 유도한다.
export function AutoTradingStatusCard({ slots, coins }: AutoTradingStatusCardProps) {
  const activeSlots = slots.filter((slot) => slot.is_active);

  return (
    <Link to="/auto" className="dashboard-card auto-status-card">
      <p className="dashboard-card-label">자동매매 상태</p>
      {activeSlots.length === 0 ? (
        <p className="dashboard-empty-text">운용 중인 자동매매 없음</p>
      ) : (
        <ul className="auto-status-list">
          {activeSlots.map((slot) => {
            const coin = coins.find((c) => c.symbol === slot.coin_symbol);
            return (
              <li key={slot.id} className="auto-status-item">
                <span>{coin?.korean_name ?? slot.coin_symbol}</span>
                <span className="auto-slot-badge">{STRATEGY_TYPE_LABEL[slot.strategy_type]}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Link>
  );
}
