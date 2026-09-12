"""03-manual-trading Control 계층 — 코인 목록/시세 조회.

시세는 price_stream.py의 상시 캐시를 그대로 읽는다 (00-overview.md 3장 — 별도 조회
없이 이미 항상 갱신되고 있는 캐시를 재사용).
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Coin
from app.services import price_stream


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼을 조회하려는 경우."""


def list_coins_with_price(db: Session) -> list[dict]:
    coins = db.scalars(select(Coin).where(Coin.is_active).order_by(Coin.symbol)).all()
    result = []
    for coin in coins:
        cached = price_stream.get_cached_price(coin.symbol)
        result.append(
            {
                "symbol": coin.symbol,
                "korean_name": coin.korean_name,
                "english_name": coin.english_name,
                "current_price": Decimal(str(cached["trade_price"])) if cached else None,
                "change_rate": Decimal(str(cached["signed_change_rate"])) if cached else None,
            }
        )
    return result


def get_market_code(db: Session, symbol: str) -> str:
    coin = db.get(Coin, symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()
    return coin.market_code
