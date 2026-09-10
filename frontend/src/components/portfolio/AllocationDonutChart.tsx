import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { PriceTick } from "../../types/dashboard";
import type { HoldingItem } from "../../types/portfolio";

// dataviz 스킬 카테고리 팔레트(dark, 5슬롯) — 이 앱의 --surface(#2a2a27) 배경 기준으로
// validate_palette.js 통과 확인(CVD/명도대비 전부 PASS). 원화·기타는 하이(hue) 정체성이
// 아니므로 팔레트 밖 중립 회색을 쓴다.
const COIN_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"];
const CASH_COLOR = "#8f8f89";
const OTHER_COLOR = "#5a5a56";
const SURFACE_COLOR = "#2a2a27"; // --surface 리터럴값 (SVG stroke 속성엔 var()를 안 쓴다)
const MAX_COIN_SLICES = 5;

interface AllocationSlice {
  key: string;
  label: string;
  value: number;
  color: string;
}

interface AllocationDonutChartProps {
  krwBalance: number;
  holdings: HoldingItem[];
  prices: Record<string, PriceTick>;
}

// 08-portfolio.md 2-C 자산 배분 도넛 차트 — 별도 API 없이 holdings 응답 + 보유 원화로
// 화면에서 파생시킨다(계획 문서 결정 — 표와 도넛이 실시간 시세 기준으로 항상 일치해야 하므로).
export function AllocationDonutChart({ krwBalance, holdings, prices }: AllocationDonutChartProps) {
  const valuations = holdings
    .map((holding) => {
      const live = prices[holding.coin_symbol]?.trade_price;
      const price = live ?? Number(holding.current_price);
      return {
        symbol: holding.coin_symbol,
        label: holding.korean_name,
        value: Number(holding.quantity) * price,
      };
    })
    .filter((item) => item.value > 0)
    .sort((a, b) => b.value - a.value);

  const shown = valuations.slice(0, MAX_COIN_SLICES);
  const rest = valuations.slice(MAX_COIN_SLICES);
  const otherTotal = rest.reduce((sum, item) => sum + item.value, 0);

  // 색은 평가액 순위가 아니라 심볼의 알파벳 순서로 고정 배정한다 — 실시간 시세로 두 코인의
  // 순위가 뒤바뀌어도 같은 코인이 같은 색을 유지해야 하기 때문이다("색은 엔티티를 따르고
  // 순위를 따르지 않는다", dataviz 스킬).
  const colorOrder = shown.map((item) => item.symbol).sort();
  const slices: AllocationSlice[] = [
    { key: "krw", label: "원화", value: krwBalance, color: CASH_COLOR },
    ...shown.map((item) => ({
      key: item.symbol,
      label: item.label,
      value: item.value,
      color: COIN_COLORS[colorOrder.indexOf(item.symbol) % COIN_COLORS.length],
    })),
  ];
  if (otherTotal > 0) {
    slices.push({ key: "other", label: "기타", value: otherTotal, color: OTHER_COLOR });
  }

  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  if (total <= 0) {
    return <p className="dashboard-empty-text">표시할 자산이 없습니다.</p>;
  }

  return (
    <div className="portfolio-donut-wrap">
      <ResponsiveContainer width="100%" height={200}>
        <PieChart>
          <Pie
            data={slices}
            dataKey="value"
            nameKey="label"
            innerRadius={55}
            outerRadius={80}
            paddingAngle={2}
            stroke={SURFACE_COLOR}
            strokeWidth={2}
          >
            {slices.map((slice) => (
              <Cell key={slice.key} fill={slice.color} />
            ))}
          </Pie>
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload || payload.length === 0) return null;
              const slice = payload[0].payload as AllocationSlice;
              return (
                <div className="portfolio-donut-tooltip">
                  <p>{slice.label}</p>
                  <p>
                    {Math.round(slice.value).toLocaleString("ko-KR")}원 (
                    {((slice.value / total) * 100).toFixed(1)}%)
                  </p>
                </div>
              );
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <ul className="portfolio-donut-legend">
        {slices.map((slice) => (
          <li key={slice.key} className="portfolio-donut-legend-item">
            <span className="portfolio-donut-legend-dot" style={{ background: slice.color }} />
            <span className="portfolio-donut-legend-label">{slice.label}</span>
            <span className="portfolio-donut-legend-pct">{((slice.value / total) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
