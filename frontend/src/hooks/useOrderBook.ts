import { useEffect, useState } from "react";
import type { OrderBookSnapshot } from "../types/orderbook";

const WS_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /^http/,
  "ws",
);
const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 5000;

export type OrderBookStatus = "connecting" | "open" | "failed";

// 03-manual-trading 3열 호가창 — usePriceStream과 동일한 온디맨드 재연결 패턴을 따르되,
// 대상이 여러 심볼(query string)이 아니라 화면이 보고 있는 심볼 하나(path param)다
// (00-overview.md 3장 — 호가는 상시 구독 대상이 아니라 온디맨드로만 구독).
export function useOrderBook(symbol: string | null) {
  const [orderBook, setOrderBook] = useState<OrderBookSnapshot | null>(null);
  const [status, setStatus] = useState<OrderBookStatus>("connecting");

  useEffect(() => {
    setOrderBook(null);
    if (!symbol) {
      setStatus("open");
      return;
    }

    let attempt = 0;
    let stopped = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus("connecting");
      socket = new WebSocket(`${WS_BASE_URL}/ws/orderbook/${encodeURIComponent(symbol)}`);

      socket.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      socket.onmessage = (event) => {
        setOrderBook(JSON.parse(event.data));
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
  }, [symbol]);

  return { orderBook, status };
}
