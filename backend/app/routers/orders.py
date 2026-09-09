"""03-manual-trading Boundary 계층 — /api/orders/*. Control(services/orders.py)만 호출한다."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas.orders import OrderCreateRequest, OrderResponse
from app.services.auth import get_current_user
from app.services.orders import (
    CoinNotFoundError,
    InsufficientBalanceError,
    InsufficientHoldingError,
    InvalidOrderInputError,
    OrderNotCancelableError,
    OrderNotFoundError,
    PriceUnavailableError,
    cancel_order,
    create_order,
    list_order_history,
    list_pending_orders,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _to_response(order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        coin_symbol=order.coin_symbol,
        side=order.side,
        order_type=order.order_type,
        price=str(order.price),
        quantity=str(order.quantity),
        status=order.status,
        source=order.source,
        realized_profit=str(order.realized_profit) if order.realized_profit is not None else None,
        fee=str(order.fee),
        trigger_price=str(order.trigger_price) if order.trigger_price is not None else None,
        trigger_direction=order.trigger_direction,
        created_at=order.created_at,
        filled_at=order.filled_at,
    )


@router.post("", response_model=OrderResponse, status_code=http_status.HTTP_201_CREATED)
def post_order(
    payload: OrderCreateRequest,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> OrderResponse:
    try:
        quantity = Decimal(payload.quantity)
        price = Decimal(payload.price) if payload.price is not None else None
        trigger_price = Decimal(payload.trigger_price) if payload.trigger_price is not None else None
    except InvalidOperation:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바르게 입력해주세요.")

    try:
        order = create_order(
            db,
            user_id=current_user.id,
            coin_symbol=payload.coin_symbol.upper(),
            side=payload.side,
            order_type=payload.order_type,
            quantity=quantity,
            price=price,
            trigger_price=trigger_price,
        )
    except CoinNotFoundError:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 코인입니다."
        )
    except InvalidOrderInputError:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="올바르게 입력해주세요.")
    except InsufficientBalanceError:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="보유 원화가 부족합니다. 입출금 화면에서 충전 후 이용해주세요.",
        )
    except InsufficientHoldingError as e:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"보유 {e.korean_name} 수량이 부족합니다.",
        )
    except PriceUnavailableError:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="주문 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )
    return _to_response(order)


@router.delete("/{order_id}", status_code=http_status.HTTP_204_NO_CONTENT)
def delete_order(
    order_id: int,
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> None:
    try:
        cancel_order(db, current_user.id, order_id)
    except OrderNotFoundError:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="존재하지 않는 주문입니다.")
    except OrderNotCancelableError:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="이미 처리된 주문입니다."
        )


@router.get("", response_model=list[OrderResponse])
def get_orders(
    status: str = Query("pending"),
    coin_symbol: str | None = Query(None),
    db: Session = Depends(get_session),
    current_user=Depends(get_current_user),
) -> list[OrderResponse]:
    if status == "pending":
        orders = list_pending_orders(db, current_user.id)
    elif status == "history":
        symbol = coin_symbol.upper() if coin_symbol else None
        orders = list_order_history(db, current_user.id, coin_symbol=symbol)
    else:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail="지원하지 않는 status 값입니다."
        )
    return [_to_response(order) for order in orders]
