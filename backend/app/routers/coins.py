"""03-manual-trading Boundary 계층 — /api/coins/*. Control(services/coins.py, services/orders.py)만 호출한다."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.coins import AvailableBalanceResponse, CoinResponse
from app.services import orders as orders_service
from app.services.auth import get_current_user
from app.services.coins import CoinNotFoundError, get_market_code, list_coins_with_price

router = APIRouter(prefix="/api/coins", tags=["coins"])


@router.get("", response_model=list[CoinResponse])
def get_coins(
    db: Session = Depends(get_session), current_user=Depends(get_current_user)
) -> list[CoinResponse]:
    coins = list_coins_with_price(db)
    return [
        CoinResponse(
            symbol=coin["symbol"],
            korean_name=coin["korean_name"],
            english_name=coin["english_name"],
            current_price=str(coin["current_price"]) if coin["current_price"] is not None else None,
            change_rate=str(coin["change_rate"]) if coin["change_rate"] is not None else None,
        )
        for coin in coins
    ]


@router.get("/{symbol}/balance", response_model=AvailableBalanceResponse)
def get_available_balance(
    symbol: str,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> AvailableBalanceResponse:
    symbol = symbol.upper()
    try:
        get_market_code(db, symbol)
    except CoinNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다."
        )
    return AvailableBalanceResponse(
        available_krw=str(orders_service.get_available_krw(db, current_user.id)),
        available_quantity=str(orders_service.get_available_quantity(db, current_user.id, symbol)),
    )
