"""확장판 8단계 — 관리자 API 응답 스키마 (docs-scale/05-admin.md).

금액은 다른 API와 같이 문자열로 내려 정밀도를 보존한다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.orders import OrderResponse
from app.schemas.portfolio import HoldingItem
from app.schemas.strategy_slots import StrategySlotResponse
from app.schemas.wallet import TransactionResponse


class AdminUserItem(BaseModel):
    id: int
    email: str
    role: str
    status: str
    created_at: datetime
    active_slot_count: int
    krw_balance: str
    total_valuation: str


class AdminUserListResponse(BaseModel):
    items: list[AdminUserItem]
    total: int


class AdminUserSummary(BaseModel):
    krw_balance: str
    withdrawable_krw: str
    coin_valuation: str
    total_valuation: str
    net_deposit: str


class AdminUserDetailResponse(BaseModel):
    id: int
    email: str
    role: str
    status: str
    created_at: datetime
    summary: AdminUserSummary
    holdings: list[HoldingItem]
    slots: list[StrategySlotResponse]
    pending_orders: list[OrderResponse]
    recent_orders: list[OrderResponse]
    recent_transactions: list[TransactionResponse]


class AdminUserStatusRequest(BaseModel):
    status: Literal["active", "suspended"]


class AdminUserStatusResponse(BaseModel):
    status: str
    changed: bool
    deactivated_slot_ids: list[int]
    canceled_order_ids: list[int]


class ShardCoverage(BaseModel):
    applicable: bool
    missing: list[int] | None  # None = 조회 실패(모름). 빈 목록과 다르다


class HeartbeatItem(BaseModel):
    role: str
    shard_id: int | None
    process_id: str
    last_tick_at: datetime
    seconds_since_tick: int
    stale: bool
    last_duration_ms: int
    max_duration_ms: int
    over_budget_count: int
    item_count: int
    db_connections: int
    error_count: int
    skip_count: int


class RateLimitBucket(BaseModel):
    tokens: float
    capacity: float


class RateLimitStatus(BaseModel):
    backend: str
    penalty: float
    buckets: dict[str, RateLimitBucket]


class SystemOverviewResponse(BaseModel):
    shard_count: int
    worker_coverage: ShardCoverage
    matcher_coverage: ShardCoverage
    heartbeats: list[HeartbeatItem]
    superseded_heartbeat_rows: int  # 같은 역할·샤드의 더 최신 행에 가려진 과거 프로세스 행 수
    active_users: int
    suspended_users: int
    active_slots: int
    pending_orders: int
    upbit_rate_limit: RateLimitStatus | None  # None = Redis 조회 실패


class AuditLogItem(BaseModel):
    id: int
    actor_user_id: int | None  # 행위자가 탈퇴했거나 CLI 작업이면 None
    actor_email: str | None
    action: str
    target_type: str
    target_id: int
    detail: dict | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    total: int
