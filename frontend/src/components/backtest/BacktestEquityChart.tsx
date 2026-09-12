import { useEffect, useRef, useState } from "react";
import {
  createChart,
  createSeriesMarkers,
  LineSeries,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { BacktestTradeOut, EquityPointOut } from "../../types/backtest";

// 매수(빨강)/매도(파랑) — 06-backtesting.md 3-B절. dashboard-trade-badge(.is-buy/.is-sell)와
// 같은 색으로 맞춘다(이 화면 전체의 매수·매도 색 관례).
const BUY_COLOR = "#e5484d";
const SELL_COLOR = "#4d8de5";
const LINE_COLOR = "#1d9e75";

interface BacktestEquityChartProps {
  equityCurve: EquityPointOut[];
  trades: BacktestTradeOut[];
  onSelectTrades: (trades: BacktestTradeOut[]) => void;
}

function toUtcTimestamp(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

// 06-backtesting.md 3-B절 "수익 곡선 차트 — 매수/매도 마커, 클릭 시 체결상세 팝업". lightweight-
// charts v5의 `createSeriesMarkers` 플러그인을 쓰는 이 프로젝트 첫 사례다(CandleChart.tsx는
// 캔들+거래량만 그리고 마커를 쓰지 않는다).
export function BacktestEquityChart({ equityCurve, trades, onSelectTrades }: BacktestEquityChartProps) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  // 마커 시각 → 그 시각에 체결된 거래 목록. 그리드는 한 캔들에서 여러 라인이 동시에 체결될
  // 수 있어 시각 하나에 여러 건이 몰릴 수 있다 (strategy_engine/grid.py evaluate 참고).
  const tradesByTimeRef = useRef<Map<UTCTimestamp, BacktestTradeOut[]>>(new Map());

  const onSelectTradesRef = useRef(onSelectTrades);
  onSelectTradesRef.current = onSelectTrades;

  useEffect(() => {
    if (!container) return;

    const chart = createChart(container, {
      layout: { background: { color: "transparent" }, textColor: "#9a9a96" },
      grid: { vertLines: { color: "#3d3d3a" }, horzLines: { color: "#3d3d3a" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      height: 320,
    });

    const series = chart.addSeries(LineSeries, {
      color: LINE_COLOR,
      lineWidth: 2,
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);

    const handleResize = () => chart.applyOptions({ width: container.clientWidth });
    window.addEventListener("resize", handleResize);
    handleResize();

    chart.subscribeClick((param) => {
      if (param.time === undefined) return;
      const list = tradesByTimeRef.current.get(param.time as UTCTimestamp);
      if (list && list.length > 0) {
        onSelectTradesRef.current(list);
      }
    });

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      seriesRef.current = null;
      markersRef.current = null;
    };
    // onSelectTrades는 부모 렌더마다 새로 생성될 수 있는 콜백이라, 클릭 핸들러 등록은 마운트
    // 시 1회만 하고 최신 콜백은 위 ref로 참조한다 — 매 렌더 차트를 다시 만들지 않기 위함.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container]);

  useEffect(() => {
    if (!seriesRef.current || !markersRef.current) return;

    const points: LineData[] = equityCurve.map((point) => ({
      time: toUtcTimestamp(point.at),
      value: Number(point.asset),
    }));
    seriesRef.current.setData(points);

    const tradesByTime = new Map<UTCTimestamp, BacktestTradeOut[]>();
    for (const trade of trades) {
      const time = toUtcTimestamp(trade.executed_at);
      const list = tradesByTime.get(time);
      if (list) list.push(trade);
      else tradesByTime.set(time, [trade]);
    }
    tradesByTimeRef.current = tradesByTime;

    const markers: SeriesMarker<Time>[] = [];
    for (const [time, list] of tradesByTime) {
      // 같은 시각에 매수·매도가 섞여 있으면(그리드) 매도를 대표로 보여준다 — 실현손익이 있는
      // 쪽이 더 궁금한 정보라서다. 클릭하면 onSelectTrades가 그 시각의 전체 목록을 넘긴다.
      const representative = list.find((trade) => trade.side === "sell") ?? list[0];
      markers.push({
        time,
        position: representative.side === "buy" ? "belowBar" : "aboveBar",
        shape: representative.side === "buy" ? "arrowUp" : "arrowDown",
        color: representative.side === "buy" ? BUY_COLOR : SELL_COLOR,
        size: 1,
      });
    }
    markersRef.current.setMarkers(markers);
  }, [equityCurve, trades, container]);

  if (equityCurve.length === 0) {
    return <div className="dashboard-chart-empty">실행 결과가 없습니다.</div>;
  }

  return <div ref={setContainer} className="dashboard-chart-container" />;
}
