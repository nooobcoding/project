"""02-dashboard 요청/응답 DTO (Boundary 계층 계약, models와 별개로 유지).

금액·수량·비율 필드는 문자열로 반환한다 (02-coding-conventions.md 9절 — 프론트 부동소수점
오차 방지, JS로는 문자열로 받고 화면 표시 직전에만 포매팅).
"""

from datetime import datetime

from pydantic import BaseModel


class DashboardSummaryResponse(BaseModel):
    krw_balance: str
    coin_valuation: str
    profit_pct: str


class WatchlistItemResponse(BaseModel):
    coin_symbol: str
    sort_order: int


class WatchlistCreateRequest(BaseModel):
    coin_symbol: str


class RecentTradeResponse(BaseModel):
    """03-manual-trading 완료 전까지 목록은 항상 비어 있다 (02-dashboard.md 5장)."""

    side: str
    coin_symbol: str
    price: str
    quantity: str
    filled_at: datetime
