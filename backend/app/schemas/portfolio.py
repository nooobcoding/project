"""08-portfolio 응답 DTO.

금액·수량 필드는 문자열로 반환한다 (02-coding-conventions.md 9절).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PortfolioSummaryResponse(BaseModel):
    krw_balance: str
    coin_valuation: str
    net_deposit: str


class CoinRef(BaseModel):
    symbol: str
    korean_name: str


class HoldingItem(BaseModel):
    coin_symbol: str
    korean_name: str
    quantity: str
    avg_buy_price: str
    current_price: str
    valuation: str
    profit: str
    profit_pct: str


class TradeItem(BaseModel):
    id: int
    coin_symbol: str
    korean_name: str
    side: Literal["buy", "sell"]
    source: Literal["manual", "auto"]
    price: str
    quantity: str
    filled_at: datetime


class TradeListResponse(BaseModel):
    items: list[TradeItem]
    total: int
    traded_coins: list[CoinRef]


class MonthlyProfit(BaseModel):
    month: str
    profit: str


class PortfolioReportResponse(BaseModel):
    start: datetime | None
    end: datetime
    most_traded_coin: CoinRef | None
    monthly_profits: list[MonthlyProfit]
