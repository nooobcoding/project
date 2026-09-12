// backend/app/services/orderbook_stream.py가 중계하는 Upbit 호가 원본 메시지 그대로.
// 저장/집계되지 않는 실시간 값이라 number를 유지한다 (types/dashboard.ts의 PriceTick과 동일 전례).

export interface OrderBookUnit {
  ask_price: number;
  bid_price: number;
  ask_size: number;
  bid_size: number;
}

export interface OrderBookSnapshot {
  code: string;
  total_ask_size: number;
  total_bid_size: number;
  orderbook_units: OrderBookUnit[];
  timestamp: number;
}
