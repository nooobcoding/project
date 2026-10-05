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
