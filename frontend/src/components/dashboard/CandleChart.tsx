import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  type CandlestickData,
  type HistogramData,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { getCandles } from "../../api/candles";
import { useAuth } from "../../hooks/useAuth";
import type { CandleInterval } from "../../types/candles";
import type { PriceTick } from "../../types/dashboard";

const RISE_COLOR = "#e5484d";
const FALL_COLOR = "#1d9e75";

// services/candles.py의 _INTERVAL_SECONDS와 1:1 대응 — 실시간 틱을 진행 중인 봉에 합칠 때
// 어느 시각 구간(bucket)에 속하는지 판단하는 데 쓴다.
const INTERVAL_SECONDS: Record<CandleInterval, number> = {
  "1m": 60,
  "10m": 600,
  "30m": 1800,
  "1h": 3600,
  "1d": 86400,
};

interface CandleChartProps {
  symbol: string | null;
  tick: PriceTick | null;
  interval: CandleInterval;
}

interface ChartPoint {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// 실 과거 일봉(01-erd.md `candles`)을 GET /api/coins/{symbol}/candles로 불러와 채우고,
// 그 위에 /ws/prices 틱으로 당일 봉만 실시간 갱신한다. 03-manual-trading이 그대로
// 재사용할 인프라를 02에서 앞당겨 구현했다.
export function CandleChart({ symbol, tick, interval }: CandleChartProps) {
  const { token } = useAuth();
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const pointsRef = useRef<ChartPoint[]>([]);

  useEffect(() => {
    if (!container) return;

    const chart = createChart(container, {
      layout: { background: { color: "transparent" }, textColor: "#9a9a96" },
      grid: { vertLines: { color: "#3d3d3a" }, horzLines: { color: "#3d3d3a" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      height: 320,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: RISE_COLOR,
      downColor: FALL_COLOR,
      borderVisible: false,
      wickUpColor: RISE_COLOR,
      wickDownColor: FALL_COLOR,
      priceFormat: { type: "price", precision: 0, minMove: 1 }, // 원화는 소수점이 없다
    });
    candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.3 } });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume", precision: 2, minMove: 0.01 },
      priceScaleId: "volume",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth });
    };
    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [container]);

  useEffect(() => {
    // container가 나중에 나타나는 경우(코인 없다가 처음 추가되는 시점)에도 위 mount
    // effect가 먼저 실행되어 series를 만들어준 뒤 이 effect가 실행된다(선언 순서 보장).
    if (!symbol || !token || !candleSeriesRef.current || !volumeSeriesRef.current) {
      return;
    }
    let cancelled = false;
    getCandles(token, symbol, interval)
      .then((candles) => {
        if (cancelled) return;
        const points: ChartPoint[] = candles.map((candle) => ({
          time: Math.floor(new Date(candle.opened_at).getTime() / 1000) as UTCTimestamp,
          open: Number(candle.open),
          high: Number(candle.high),
          low: Number(candle.low),
          close: Number(candle.close),
          volume: Number(candle.volume),
        }));
        pointsRef.current = points;
        candleSeriesRef.current?.setData(
          points.map(
            (p): CandlestickData => ({
              time: p.time,
              open: p.open,
              high: p.high,
              low: p.low,
              close: p.close,
            }),
          ),
        );
        volumeSeriesRef.current?.setData(
          points.map(
            (p): HistogramData => ({
              time: p.time,
              value: p.volume,
              color: p.close >= p.open ? RISE_COLOR : FALL_COLOR,
            }),
          ),
        );
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [symbol, token, container, interval]);

  useEffect(() => {
    if (!tick || tick.symbol !== symbol || !candleSeriesRef.current || !volumeSeriesRef.current) {
      return;
    }
    const points = pointsRef.current;
    if (points.length === 0) {
      return;
    }

    const intervalSeconds = INTERVAL_SECONDS[interval];
    const tickTime = Math.floor(tick.timestamp / 1000);
    const bucketStart = (Math.floor(tickTime / intervalSeconds) * intervalSeconds) as UTCTimestamp;
    const last = points[points.length - 1];

    if (last.time === bucketStart) {
      last.high = Math.max(last.high, tick.trade_price);
      last.low = Math.min(last.low, tick.trade_price);
      last.close = tick.trade_price;
      last.volume += tick.trade_volume;
    } else if (bucketStart > last.time) {
      points.push({
        time: bucketStart,
        open: tick.trade_price,
        high: tick.trade_price,
        low: tick.trade_price,
        close: tick.trade_price,
        volume: tick.trade_volume,
      });
    } else {
      return; // 캐시된 과거 봉보다 오래된 틱 — 무시
    }

    const updated = points[points.length - 1];
    candleSeriesRef.current.update({
      time: updated.time,
      open: updated.open,
      high: updated.high,
      low: updated.low,
      close: updated.close,
    });
    volumeSeriesRef.current.update({
      time: updated.time,
      value: updated.volume,
      color: updated.close >= updated.open ? RISE_COLOR : FALL_COLOR,
    });
  }, [tick, symbol, interval]);

  if (!symbol) {
    // 대시보드는 관심 코인 추가 전, 03-manual-trading은 코인 목록 로딩 전에 각각 보일 수 있어
    // 두 화면 모두에 맞는 일반적인 문구를 쓴다.
    return <div className="dashboard-chart-empty">코인을 선택하면 시세 차트가 표시됩니다.</div>;
  }

  return <div ref={setContainer} className="dashboard-chart-container" />;
}
