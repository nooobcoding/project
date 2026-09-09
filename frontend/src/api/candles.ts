import { apiFetch } from "./client";
import type { Candle, CandleInterval } from "../types/candles";

export function getCandles(
  token: string,
  symbol: string,
  interval: CandleInterval,
): Promise<Candle[]> {
  return apiFetch<Candle[]>(
    `/api/coins/${encodeURIComponent(symbol)}/candles?interval=${interval}`,
    { token },
  );
}
