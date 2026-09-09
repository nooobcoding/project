// backend/app/schemas/orders.py 1:1 대응 (docs/02-coding-conventions.md 9장)

export type OrderSide = "buy" | "sell";
export type OrderType = "limit" | "market" | "reserved";
export type OrderStatus = "pending" | "filled" | "canceled";
export type TriggerDirection = "rising" | "falling";

export interface Order {
  id: number;
  coin_symbol: string;
  side: OrderSide;
  order_type: OrderType;
  price: string;
  quantity: string;
  status: OrderStatus;
  source: "manual" | "auto";
  realized_profit: string | null;
  fee: string;
  trigger_price: string | null;
  trigger_direction: TriggerDirection | null;
  strategy_slot_id: number | null;
  created_at: string;
  filled_at: string | null;
}

export interface OrderCreateInput {
  coin_symbol: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: string;
  price?: string;
  trigger_price?: string;
}
