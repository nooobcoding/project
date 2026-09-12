"""03-manual-trading 요청/응답 DTO — 주문.

금액·수량·수수료·실현손익 필드는 문자열로 반환한다 (02-coding-conventions.md 9절).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class OrderCreateRequest(BaseModel):
    coin_symbol: str
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "market", "reserved"]
    quantity: str
    price: str | None = None
    trigger_price: str | None = None


class OrderResponse(BaseModel):
    id: int
    coin_symbol: str
    side: str
    order_type: str
    price: str
    quantity: str
    status: str
    source: str
    realized_profit: str | None
    fee: str
    trigger_price: str | None
    trigger_direction: str | None
    strategy_slot_id: int | None
    created_at: datetime
    filled_at: datetime | None
