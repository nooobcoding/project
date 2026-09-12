// backend/app/schemas/portfolio.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export interface PortfolioSummary {
  krw_balance: string;
  coin_valuation: string;
  net_deposit: string;
}

export interface CoinRef {
  symbol: string;
  korean_name: string;
}

export interface HoldingItem {
  coin_symbol: string;
  korean_name: string;
  quantity: string;
  avg_buy_price: string;
  current_price: string;
  valuation: string;
  profit: string;
  profit_pct: string;
}

export type TradeSide = "buy" | "sell";
export type TradeSource = "manual" | "auto";

export interface TradeItem {
  id: number;
  coin_symbol: string;
  korean_name: string;
  side: TradeSide;
  source: TradeSource;
  price: string;
  quantity: string;
  filled_at: string;
}

export interface TradeListResponse {
  items: TradeItem[];
  total: number;
  traded_coins: CoinRef[];
}

export interface MonthlyProfit {
  month: string;
  profit: string;
}

export type ReportPeriod = "1m" | "3m" | "6m" | "1y" | "all";

export interface PortfolioReport {
  start: string | null;
  end: string;
  most_traded_coin: CoinRef | null;
  monthly_profits: MonthlyProfit[];
}
