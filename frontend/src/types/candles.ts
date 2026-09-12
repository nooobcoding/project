// backend/app/schemas/candles.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export type CandleInterval = "1m" | "10m" | "30m" | "1h" | "1d";

export interface Candle {
  opened_at: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}
