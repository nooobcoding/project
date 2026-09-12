import { useEffect, useState } from "react";
import type { PriceTick } from "../types/dashboard";

const WS_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /^http/,
  "ws",
);
const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 5000;

export type PriceStreamStatus = "connecting" | "open" | "failed";

// 02-dashboard.md 3장 인터랙션 표 — WebSocket 연결 끊김 시 3회 5초 간격 재연결, 실패 시 배너.
export function useWatchlistPrices(symbols: string[]) {
  const [prices, setPrices] = useState<Record<string, PriceTick>>({});
  const [status, setStatus] = useState<PriceStreamStatus>("connecting");
  const symbolsKey = symbols.slice().sort().join(",");

  useEffect(() => {
    if (symbolsKey === "") {
      setStatus("open");
      return;
    }

    let attempt = 0;
    let stopped = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus("connecting");
      socket = new WebSocket(`${WS_BASE_URL}/ws/prices?symbols=${symbolsKey}`);

      socket.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      socket.onmessage = (event) => {
        const tick: PriceTick = JSON.parse(event.data);
        setPrices((prev) => ({ ...prev, [tick.symbol]: tick }));
      };
      socket.onclose = () => {
        if (stopped) return;
        if (attempt < MAX_RECONNECT_ATTEMPTS) {
          attempt += 1;
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        } else {
          setStatus("failed");
        }
      };
      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, [symbolsKey]);

  return { prices, status };
}
