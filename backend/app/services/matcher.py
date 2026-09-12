"""09-execution-engine Control 계층 — orders.status='pending'을 체결로 전환시키는 유일한 주체.

지정가는 backend/app/services/price_stream.py의 시세 스트림 훅(run_matching_for_symbol)이,
시장가는 services/orders.py의 create_order가 같은 요청 트랜잭션 안에서 fill_order를 직접
호출해 체결시킨다. 두 경로 모두 fill_order의 동일한 체결 후처리 절차를 공유한다
(09-execution-engine.md 3.2절).
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.constants import TRADING_FEE_RATE
from app.database import session_scope
from app.models import Balance, Holding, Order


def _calculate_fee(price: Decimal, quantity: Decimal) -> Decimal:
    """체결 수수료(원화)를 계산한다 (01-erd.md 3.2절)."""
    return (price * quantity * TRADING_FEE_RATE).quantize(Decimal("0.0001"))


def _limit_condition_met(side: str, order_price: Decimal, current_price: Decimal) -> bool:
    """지정가 주문의 체결 조건을 판정한다 (09-execution-engine.md 3장).

    매수는 현재가가 지정가 이하로 내려왔을 때, 매도는 현재가가 지정가 이상으로
    올랐을 때 체결된다.
    """
    if side == "buy":
        return current_price <= order_price
    return current_price >= order_price


def _apply_holdings(db: Session, order: Order) -> Decimal:
    """holdings를 갱신하고, 갱신 직전 avg_buy_price를 반환한다.

    매도 체결의 realized_profit은 이 갱신 직전 값을 기준으로 계산해야 하므로
    (01-erd.md 234행 규칙), 호출자가 이 반환값을 그대로 써야 한다.
    """
    holding = db.get(Holding, (order.user_id, order.coin_symbol))
    if holding is None:
        # quantity/avg_buy_price의 컬럼 default는 flush 시점에만 적용되므로, autoflush=False인
        # 세션에서 곧바로 연산에 쓰려면 여기서 직접 초기값을 채워야 한다.
        holding = Holding(
            user_id=order.user_id,
            coin_symbol=order.coin_symbol,
            quantity=Decimal(0),
            avg_buy_price=Decimal(0),
        )
        db.add(holding)

    avg_buy_price_before = holding.avg_buy_price

    if order.side == "buy":
        # 매수 수수료 포함 취득원가로 가중평균 재계산 (01-erd.md 3.2절)
        cost_before = holding.quantity * holding.avg_buy_price
        cost_added = order.price * order.quantity * (1 + TRADING_FEE_RATE)
        new_quantity = holding.quantity + order.quantity
        holding.avg_buy_price = (cost_before + cost_added) / new_quantity
        holding.quantity = new_quantity
    else:
        holding.quantity -= order.quantity
        if holding.quantity <= 0:
            holding.quantity = Decimal(0)
            holding.avg_buy_price = Decimal(0)

    return avg_buy_price_before


def _apply_balance(db: Session, order: Order) -> None:
    """balances.krw_balance를 갱신한다 (01-erd.md 3.2절)."""
    balance = db.get(Balance, order.user_id)
    amount = order.price * order.quantity
    if order.side == "buy":
        balance.krw_balance -= amount * (1 + TRADING_FEE_RATE)
    else:
        balance.krw_balance += amount * (1 - TRADING_FEE_RATE)
    balance.updated_at = datetime.now(timezone.utc)


def _apply_auto_trading_hook(db: Session, order: Order) -> None:
    """source='auto' 체결의 notifications/strategy_slots.state 갱신 지점.

    07-auto-trading 미구현 상태라 source는 항상 'manual'이다. 07 구현 시
    09-execution-engine.md 3.2절 5단계(알림 적재 + state.position 갱신)를 여기에 채운다.
    """
    if order.source != "auto":
        return


def fill_order(db: Session, order: Order, fill_price: Decimal) -> bool:
    """주문 하나를 체결 처리한다 (09-execution-engine.md 3.2절 순서 그대로).

    조건부 UPDATE로 pending 상태를 선점한 뒤에만 후속 절차를 수행하므로, 같은 주문이
    체결 엔진과 취소 요청 양쪽에서 동시에 처리 시도되어도 한쪽만 성공한다 (3.1절).
    """
    fee = _calculate_fee(fill_price, order.quantity)
    result = db.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == "pending")
        .values(status="filled", filled_at=datetime.now(timezone.utc), price=fill_price, fee=fee)
    )
    if result.rowcount == 0:
        db.commit()
        return False

    order.status = "filled"
    order.filled_at = datetime.now(timezone.utc)
    order.price = fill_price
    order.fee = fee

    if order.side == "sell":
        avg_buy_price_before = _apply_holdings(db, order)
        # 매수 수수료가 이미 avg_buy_price에 녹아 있어 이 한 줄로 왕복 수수료가 반영된다 (01-erd.md 3.2절)
        order.realized_profit = (
            fill_price * order.quantity * (1 - TRADING_FEE_RATE)
            - avg_buy_price_before * order.quantity
        )
    else:
        _apply_holdings(db, order)

    _apply_balance(db, order)
    _apply_auto_trading_hook(db, order)

    db.commit()
    return True


def _reserved_condition_met(trigger_direction: str, trigger_price: Decimal, current_price: Decimal) -> bool:
    """예약가 주문의 감시가격 도달 여부를 판정한다.

    trigger_direction은 주문 생성 시점에 현재가 대비 감시가격 위치로 1회 확정된 값이다
    (services/orders.py create_order 참고) — 여기서 재계산하지 않는다.
    """
    if trigger_direction == "rising":
        return current_price >= trigger_price
    return current_price <= trigger_price


def _promote_reserved_orders(symbol: str, current_price: Decimal) -> None:
    """감시가격에 도달한 예약가 주문을 지정가로 승격한다 (체결은 하지 않는다).

    이 함수가 끝난 뒤 run_matching_for_symbol의 기존 지정가 후보 조회가 이어지므로,
    같은 틱에서 승격과 체결이 순차적으로 함께 일어날 수 있다.
    """
    with session_scope() as db:
        candidates = [
            (order.id, order.trigger_direction, order.trigger_price)
            for order in db.scalars(
                select(Order).where(
                    Order.coin_symbol == symbol,
                    Order.status == "pending",
                    Order.order_type == "reserved",
                )
            )
        ]

    for order_id, trigger_direction, trigger_price in candidates:
        if not _reserved_condition_met(trigger_direction, trigger_price, current_price):
            continue
        with session_scope() as db:
            # 취소 요청과의 동시 경쟁을 방지하는 조건부 UPDATE — 체결의 조건부 UPDATE와 동일 패턴
            # (09-execution-engine.md 3.1/3.3절).
            db.execute(
                update(Order)
                .where(Order.id == order_id, Order.status == "pending", Order.order_type == "reserved")
                .values(order_type="limit")
            )


def run_matching_for_symbol(symbol: str, current_price: Decimal) -> None:
    """시세 캐시 갱신 이벤트를 받아 해당 심볼의 pending 지정가 주문을 매칭한다.

    price_stream.py의 틱 수신 지점에서 호출된다 (09-execution-engine.md 2장).
    후보 조회와 개별 체결을 서로 다른 세션으로 분리해, 한 주문의 실패가 같은 틱에서
    매칭된 다른 주문에 영향을 주지 않게 한다.
    """
    _promote_reserved_orders(symbol, current_price)

    with session_scope() as db:
        # 이 세션은 with 블록을 벗어나며 커밋·종료되어 객체가 detach되므로(expire_on_commit
        # 기본값), 판정에 필요한 값만 원시 튜플로 뽑아 세션 수명과 분리한다.
        candidates = [
            (order.id, order.side, order.price)
            for order in db.scalars(
                select(Order).where(
                    Order.coin_symbol == symbol,
                    Order.status == "pending",
                    Order.order_type == "limit",
                )
            )
        ]

    for order_id, side, order_price in candidates:
        if not _limit_condition_met(side, order_price, current_price):
            continue
        with session_scope() as db:
            order = db.get(Order, order_id)
            if order is None or order.status != "pending":
                continue
            fill_order(db, order, fill_price=order.price)
