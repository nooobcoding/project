"""02-dashboard/03-manual-trading 공용 Boundary 계층 — /api/coins/{symbol}/candles.

03-manual-trading.md 6장에 명세된 경로를 그대로 사용한다. Control(services/candles.py)만 호출한다.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.candles import CandleResponse
from app.services.auth import get_current_user
from app.services.candles import CoinNotFoundError, Interval, get_candles

router = APIRouter(prefix="/api/coins", tags=["candles"])


@router.get("/{symbol}/candles", response_model=list[CandleResponse])
def get_symbol_candles(
    symbol: str,
    interval: Interval = Query("1d"),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> list[CandleResponse]:
    try:
        candles = get_candles(db, symbol.upper(), interval)
    except CoinNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다."
        )
    return [
        CandleResponse(
            opened_at=candle.opened_at,
            open=str(candle.open),
            high=str(candle.high),
            low=str(candle.low),
            close=str(candle.close),
            volume=str(candle.volume),
        )
        for candle in candles
    ]
