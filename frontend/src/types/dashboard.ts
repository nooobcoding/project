// backend/app/schemas/dashboard.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export interface DashboardSummary {
  krw_balance: string;
  coin_valuation: string;
  profit_pct: string;
}

export interface WatchlistItem {
  coin_symbol: string;
  sort_order: number;
}

export interface RecentTrade {
  side: "buy" | "sell";
  coin_symbol: string;
  price: string;
  quantity: string;
  filled_at: string;
}

// backend/app/services/price_stream.py `_to_tick()` 1:1 대응. REST와 달리 실시간
// 틱 값이라 문자열 변환(9장) 대상이 아니다 — 화면에 즉시 뿌려질 뿐 저장/집계되지 않음.
export interface PriceTick {
  symbol: string;
  trade_price: number;
  trade_volume: number;
  change: "RISE" | "EVEN" | "FALL";
  signed_change_rate: number;
  prev_closing_price: number;
  high_price: number;
  low_price: number;
  acc_trade_volume_24h: number;
  timestamp: number;
}
