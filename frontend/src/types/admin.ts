// backend/app/schemas/admin.py 1:1 대응 (docs/02-coding-conventions.md 9장)
import type { Order } from "./orders";
import type { HoldingItem } from "./portfolio";
import type { StrategySlot } from "./strategySlots";
import type { Transaction } from "./wallet";

export type UserStatus = "active" | "suspended";

export interface AdminUserItem {
  id: number;
  email: string;
  role: "user" | "admin";
  status: UserStatus;
  created_at: string;
  active_slot_count: number;
  krw_balance: string;
  total_valuation: string;
}

export interface AdminUserListResponse {
  items: AdminUserItem[];
  total: number;
}

export interface AdminUserListParams {
  status: UserStatus | null;
  hasActiveSlots: boolean | null;
  q: string;
  sort: "newest" | "oldest";
  page: number;
  pageSize: number;
}

export interface AdminUserDetail {
  id: number;
  email: string;
  role: "user" | "admin";
  status: UserStatus;
  created_at: string;
  summary: {
    krw_balance: string;
    withdrawable_krw: string;
    coin_valuation: string;
    total_valuation: string;
    net_deposit: string;
  };
  holdings: HoldingItem[];
  slots: StrategySlot[];
  pending_orders: Order[];
  recent_orders: Order[];
  recent_transactions: Transaction[];
}

export interface AdminUserStatusResult {
  status: UserStatus;
  changed: boolean;
  deactivated_slot_ids: number[];
  canceled_order_ids: number[];
}

export interface ShardCoverage {
  applicable: boolean;
  missing: number[] | null; // null = 조회 실패(모름). 빈 배열과 다르다
}

export interface HeartbeatItem {
  role: string;
  shard_id: number | null;
  process_id: string;
  last_tick_at: string;
  seconds_since_tick: number;
  stale: boolean;
  last_duration_ms: number;
  max_duration_ms: number;
  over_budget_count: number;
  item_count: number;
  db_connections: number;
  error_count: number;
  skip_count: number;
}

export interface RateLimitStatus {
  backend: string;
  penalty: number;
  buckets: Record<string, { tokens: number; capacity: number }>;
}

export interface SystemOverview {
  shard_count: number;
  worker_coverage: ShardCoverage;
  matcher_coverage: ShardCoverage;
  heartbeats: HeartbeatItem[];
  superseded_heartbeat_rows: number; // 같은 역할·샤드의 더 최신 행에 가려진 과거 프로세스 행 수
  active_users: number;
  suspended_users: number;
  active_slots: number;
  pending_orders: number;
  upbit_rate_limit: RateLimitStatus | null; // null = Redis 조회 실패
}

export interface AuditLogItem {
  id: number;
  actor_user_id: number | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: number;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogItem[];
  total: number;
}
