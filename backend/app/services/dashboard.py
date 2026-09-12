"""02-dashboard Control 계층 — 자산 요약, 관심 코인, 최근 거래 내역."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Balance, Coin, Holding, Order, Watchlist
from app.services import price_stream
from app.services.candles import CoinNotFoundError as CandleCoinNotFoundError
from app.services.candles import get_candles

MAX_WATCHLIST_SIZE = 5  # 02-dashboard.md 2-B — 관심 코인 최대 5개


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼을 등록하려는 경우."""


class WatchlistItemExistsError(Exception):
    """이미 관심 코인으로 등록된 심볼을 다시 등록하려는 경우."""


class WatchlistFullError(Exception):
    """관심 코인이 이미 최대 개수(5개)에 도달한 경우."""


def get_dashboard_summary(db: Session, user_id: int) -> dict[str, Decimal]:
    """총 평가금액 요약을 계산한다 (02-dashboard.md 2-A).

    코인 평가액은 Σ(holdings.quantity × 현재가), 평가손익(%)은 전일 대비
    Σ(holdings.quantity × 현재가) − Σ(holdings.quantity × 전일종가) 로 계산한다
    (전일종가는 candles(interval='1d')에서 조회, 별도 스냅샷 테이블 없음).
    """
    balance = db.get(Balance, user_id)
    krw_balance = balance.krw_balance if balance is not None else Decimal(0)

    holdings = db.scalars(
        select(Holding).where(Holding.user_id == user_id, Holding.quantity > 0)
    ).all()

    coin_valuation = Decimal(0)
    prev_valuation = Decimal(0)
    for holding in holdings:
        cached = price_stream.get_cached_price(holding.coin_symbol)
        current_price = Decimal(str(cached["trade_price"])) if cached else holding.avg_buy_price
        coin_valuation += holding.quantity * current_price

        try:
            recent_candles = get_candles(db, holding.coin_symbol, "1d", count=2)
        except CandleCoinNotFoundError:
            recent_candles = []
        prev_close = recent_candles[0].close if len(recent_candles) >= 2 else current_price
        prev_valuation += holding.quantity * prev_close

    profit_pct = (
        (coin_valuation - prev_valuation) / prev_valuation * 100 if prev_valuation > 0 else Decimal(0)
    )

    return {
        "krw_balance": krw_balance,
        "coin_valuation": coin_valuation,
        "profit_pct": profit_pct,
    }


def list_watchlist(db: Session, user_id: int) -> list[Watchlist]:
    return list(
        db.scalars(
            select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.sort_order)
        )
    )


def add_watchlist_item(db: Session, user_id: int, coin_symbol: str) -> Watchlist:
    coin = db.get(Coin, coin_symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()

    existing_items = list_watchlist(db, user_id)
    if any(item.coin_symbol == coin_symbol for item in existing_items):
        raise WatchlistItemExistsError()
    if len(existing_items) >= MAX_WATCHLIST_SIZE:
        raise WatchlistFullError()

    next_sort_order = max((item.sort_order for item in existing_items), default=-1) + 1
    item = Watchlist(user_id=user_id, coin_symbol=coin_symbol, sort_order=next_sort_order)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def remove_watchlist_item(db: Session, user_id: int, coin_symbol: str) -> None:
    item = db.scalar(
        select(Watchlist).where(
            Watchlist.user_id == user_id, Watchlist.coin_symbol == coin_symbol
        )
    )
    if item is not None:
        db.delete(item)
        db.commit()


def list_recent_trades(db: Session, user_id: int) -> list[dict]:
    """최근 체결 5건 (02-dashboard.md 2-C)."""
    orders = db.scalars(
        select(Order)
        .where(Order.user_id == user_id, Order.status == "filled")
        .order_by(Order.filled_at.desc())
        .limit(5)
    ).all()
    return [
        {
            "side": order.side,
            "coin_symbol": order.coin_symbol,
            "price": str(order.price),
            "quantity": str(order.quantity),
            "filled_at": order.filled_at,
        }
        for order in orders
    ]
