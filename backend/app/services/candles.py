"""캔들(OHLCV) 캐시 서비스 (01-erd.md 2장 `candles`, 02-dashboard 차트가 최초 소비자).

Upbit 캔들 REST는 1회 최대 200개·레이트리밋이 있어, 최초 조회 시 DB에 캐싱하고
이후 요청은 캐시를 우선 사용한다. 캐시의 최신 봉이 비어있을 때만(=진행 중인
구간이 아직 없을 때) Upbit에서 다시 받아온다 (01-erd.md `candles` 설명).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candle, Coin

Interval = Literal["1m", "10m", "30m", "1h", "1d"]

_INTERVAL_SECONDS: dict[Interval, int] = {
    "1m": 60,
    "10m": 600,
    "30m": 1800,
    "1h": 3600,
    "1d": 86400,
}

_MINUTE_UNITS: dict[Interval, int] = {"1m": 1, "10m": 10, "30m": 30, "1h": 60}

DEFAULT_CANDLE_COUNT = 200  # Upbit 캔들 REST 1회 최대치


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼을 조회하려는 경우."""


def _upbit_candle_url(interval: Interval) -> str:
    if interval == "1d":
        return "https://api.upbit.com/v1/candles/days"
    return f"https://api.upbit.com/v1/candles/minutes/{_MINUTE_UNITS[interval]}"


def _fetch_upbit_candles(market_code: str, interval: Interval, count: int) -> list[dict]:
    response = httpx.get(
        _upbit_candle_url(interval),
        params={"market": market_code, "count": count},
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def _upsert_candles(db: Session, symbol: str, interval: Interval, raw_candles: list[dict]) -> None:
    if not raw_candles:
        return

    opened_ats = [
        datetime.strptime(raw["candle_date_time_utc"], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        for raw in raw_candles
    ]
    existing = {
        candle.opened_at: candle
        for candle in db.scalars(
            select(Candle).where(
                Candle.coin_symbol == symbol,
                Candle.interval == interval,
                Candle.opened_at.in_(opened_ats),
            )
        )
    }

    for raw, opened_at in zip(raw_candles, opened_ats):
        candle = existing.get(opened_at)
        if candle is None:
            candle = Candle(coin_symbol=symbol, interval=interval, opened_at=opened_at)
            db.add(candle)
        candle.open = Decimal(str(raw["opening_price"]))
        candle.high = Decimal(str(raw["high_price"]))
        candle.low = Decimal(str(raw["low_price"]))
        candle.close = Decimal(str(raw["trade_price"]))
        candle.volume = Decimal(str(raw["candle_acc_trade_volume"]))
    db.commit()


def _current_bucket_start(interval: Interval, now: datetime) -> datetime:
    seconds = _INTERVAL_SECONDS[interval]
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=timezone.utc)


def get_candles(db: Session, symbol: str, interval: Interval, count: int = DEFAULT_CANDLE_COUNT) -> list[Candle]:
    """`(symbol, interval)`의 최신 `count`개 캔들을 오래된 순으로 반환한다."""
    coin = db.get(Coin, symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()

    def _load_cached() -> list[Candle]:
        return list(
            reversed(
                db.scalars(
                    select(Candle)
                    .where(Candle.coin_symbol == symbol, Candle.interval == interval)
                    .order_by(Candle.opened_at.desc())
                    .limit(count)
                ).all()
            )
        )

    cached = _load_cached()
    now = datetime.now(timezone.utc)
    bucket_start = _current_bucket_start(interval, now)

    if not cached or cached[-1].opened_at < bucket_start:
        raw_candles = _fetch_upbit_candles(coin.market_code, interval, count)
        _upsert_candles(db, symbol, interval, raw_candles)
        cached = _load_cached()

    return cached
