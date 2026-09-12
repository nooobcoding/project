// backend/app/schemas/coins.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export interface Coin {
  symbol: string;
  korean_name: string;
  english_name: string;
  current_price: string | null;
  change_rate: string | null;
}

export interface AvailableBalance {
  available_krw: string;
  available_quantity: string;
}
