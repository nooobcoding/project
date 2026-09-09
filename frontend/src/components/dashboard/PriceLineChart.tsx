import { useEffect, useRef, useState } from "react";
import {
  createChart,
  LineSeries,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PriceTick } from "../../types/dashboard";

const ONE_DAY_SECONDS = 24 * 60 * 60;

interface PriceLineChartProps {
  symbol: string | null;
  tick: PriceTick | null;
}

// 명세(02-dashboard.md 5장)에 과거 시세 조회 REST가 없고 candles 테이블도 03/06 완료
// 전까지 없다. 그래서 "1일 시세 차트"는 /ws/prices 틱을 세션 동안 누적해 그린다 —
// 접속 시점엔 빈 차트로 시작해 시간이 지나며 채워진다. 03/06에서 과거 데이터 API가
// 생기면 이 누적 로직을 교체한다.
export function PriceLineChart({ symbol, tick }: PriceLineChartProps) {
  // 컨테이너 div는 symbol이 생기기 전까진 렌더링되지 않는다(빈 상태 문구로 대체).
  // useRef는 DOM 노드가 나중에 나타나는 시점을 감지하지 못하므로, 노드가 실제로
  // 붙는 시점에 반응하도록 콜백 ref(state)로 관리한다.
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const pointsRef = useRef<LineData[]>([]);

  useEffect(() => {
    if (!container) return;

    const chart = createChart(container, {
      layout: { background: { color: "transparent" }, textColor: "#9a9a96" },
      grid: { vertLines: { color: "#3d3d3a" }, horzLines: { color: "#3d3d3a" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      height: 280,
    });
    seriesRef.current = chart.addSeries(LineSeries, {
      color: "#1d9e75",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 0, minMove: 1 }, // 원화는 소수점이 없다
    });

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth });
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      seriesRef.current = null;
    };
  }, [container]);

  useEffect(() => {
    // 코인 탭을 바꾸면 이전 코인의 누적 데이터를 초기화한다.
    pointsRef.current = [];
    seriesRef.current?.setData([]);
  }, [symbol]);

  useEffect(() => {
    if (!tick || !seriesRef.current || tick.symbol !== symbol) {
      return;
    }
    const time = Math.floor(tick.timestamp / 1000) as UTCTimestamp;
    const points = pointsRef.current;
    const last = points[points.length - 1];
    if (last && last.time === time) {
      last.value = tick.trade_price;
    } else {
      points.push({ time, value: tick.trade_price });
    }
    const cutoff = (time as number) - ONE_DAY_SECONDS;
    while (points.length > 0 && (points[0].time as number) < cutoff) {
      points.shift();
    }
    seriesRef.current.setData(points);
  }, [tick, symbol]);

  if (!symbol) {
    return <div className="dashboard-chart-empty">관심 코인을 추가하면 시세 차트가 표시됩니다.</div>;
  }

  return <div ref={setContainer} className="dashboard-chart-container" />;
}
