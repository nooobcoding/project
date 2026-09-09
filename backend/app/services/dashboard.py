"""02-dashboard Control 계층 — 자산 요약, 관심 코인, 최근 거래 내역."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Balance, Coin, Watchlist

MAX_WATCHLIST_SIZE = 5  # 02-dashboard.md 2-B — 관심 코인 최대 5개


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼을 등록하려는 경우."""


class WatchlistItemExistsError(Exception):
    """이미 관심 코인으로 등록된 심볼을 다시 등록하려는 경우."""


class WatchlistFullError(Exception):
    """관심 코인이 이미 최대 개수(5개)에 도달한 경우."""


def get_dashboard_summary(db: Session, user_id: int) -> dict[str, Decimal]:
    """총 평가금액 요약을 계산한다 (02-dashboard.md 2-A).

    코인 평가액·평가손익(%)은 holdings 테이블이 아직 없어(03-manual-trading 미구현)
    0으로 고정한다. 03 완료 후 `Σ(holdings.quantity × 현재가)` 및 전일 대비 손익
    계산으로 교체한다.
    """
    balance = db.get(Balance, user_id)
    krw_balance = balance.krw_balance if balance is not None else Decimal(0)
    coin_valuation = Decimal(0)
    return {
        "krw_balance": krw_balance,
        "coin_valuation": coin_valuation,
        "profit_pct": Decimal(0),
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


def list_recent_trades(db: Session, user_id: int) -> list:
    """최근 체결 5건 (02-dashboard.md 2-C).

    orders 테이블이 아직 없어(03-manual-trading 미구현) 항상 빈 목록을 반환한다.
    """
    return []
