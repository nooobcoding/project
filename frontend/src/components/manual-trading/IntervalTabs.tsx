import type { CandleInterval } from "../../types/candles";

const INTERVALS: { value: CandleInterval; label: string }[] = [
  { value: "1m", label: "1분" },
  { value: "10m", label: "10분" },
  { value: "30m", label: "30분" },
  { value: "1h", label: "1시간" },
  { value: "1d", label: "일" },
];

interface IntervalTabsProps {
  interval: CandleInterval;
  onChange: (interval: CandleInterval) => void;
}

// 03-manual-trading.md 2-B — 시간대 탭 (1분/10분/30분/1시간/일)
export function IntervalTabs({ interval, onChange }: IntervalTabsProps) {
  return (
    <div className="dashboard-tab-row">
      {INTERVALS.map((item) => (
        <button
          key={item.value}
          className={interval === item.value ? "dashboard-tab is-active" : "dashboard-tab"}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
