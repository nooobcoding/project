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
from app.models import (
    Balance,
    Coin,
    Holding,
    Notification,
    NotificationSetting,
    Order,
    StrategySlot,
)
from app.services import notifications as notifications_service
from app.services import slot_state
from app.strategy_engine import costs

# orders.fee NUMERIC(20,4) — 계산은 costs.py가 하고 컬럼 자릿수만 여기서 맞춘다.
_FEE_STEP = Decimal("0.0001")


def _calculate_fee(price: Decimal, quantity: Decimal) -> Decimal:
    """체결 수수료(원화)를 orders.fee 자릿수로 계산한다 (01-erd.md 3.2절).

    실체결에는 슬리피지를 적용하지 않는다 — 실시세로 체결되므로 더하면 이중 반영이 된다
    (00-overview.md 원칙 7 "의도된 비대칭"). 그래서 `costs.calc_fill_price`는 부르지 않고
    수수료 계산만 공유한다.

    **주의**: 여기서 4자리로 반올림한 값은 `orders.fee` 컬럼에 담기는 표시용이고, 실제 잔고
    증감은 `_apply_balance`가 반올림 없는 `price × quantity × (1 ± rate)`로 계산한다. 그래서
    체결 건당 최대 0.00005원까지 둘이 어긋난다 — 잔고를 거래 내역으로 재구성할 때는
    `orders.fee` 합이 아니라 이 계산식을 써야 정확히 맞는다.
    """
    return costs.calc_fee(price, quantity, TRADING_FEE_RATE).quantize(_FEE_STEP)


def _limit_condition_met(side: str, order_price: Decimal, current_price: Decimal) -> bool:
    """지정가 주문의 체결 조건을 판정한다 (09-execution-engine.md 3장).

    매수는 현재가가 지정가 이하로 내려왔을 때, 매도는 현재가가 지정가 이상으로
    올랐을 때 체결된다.
    """
    if side == "buy":
        return current_price <= order_price
    return current_price >= order_price


def _lock_user_funds(db: Session, user_id: int) -> None:
    """이 유저의 자금 관련 행 갱신을 직렬화한다 (체결 전용 잠금).

    `_apply_holdings`/`_apply_balance`는 현재 값을 읽어 "계산한 절대값"으로 UPDATE한다. 이
    읽기가 잠금 없이 이뤄지면 같은 유저의 체결 두 건이 겹칠 때 각자 같은 값을 읽고 각자
    계산한 절대값을 써서, 먼저 커밋한 쪽의 차감/가산이 통째로 사라진다(lost update).
    holdings는 그에 더해 "행이 없으면 만든다" 경로라 양쪽이 동시에 INSERT해 holdings_pkey
    유니크 위반(→ 처리되지 않은 500)이 나기도 한다. `fill_order` 상단의 조건부 UPDATE는
    "같은 주문의 중복 체결"만 막을 뿐 이 경합은 막지 못한다.

    체결은 서로 다른 스레드에서 실제로 동시에 일어난다 — 지정가는 시세 스트림 스레드
    (price_stream.py의 `asyncio.to_thread`), 시장가는 요청 스레드(orders.create_order),
    자동매매는 워커 스레드가 각각 자기 세션으로 이 함수를 통과한다.

    balances 한 행만 잠그는 것으로 충분하다 — 매수든 매도든 모든 체결이 balances를 갱신하므로
    이 행이 유저 단위 직렬화 지점이 되고, holdings를 쓰는 주체는 체결뿐이라 함께 보호된다
    (없는 holdings 행을 FOR UPDATE 해봐야 아무것도 잠기지 않으므로 INSERT 경합은 어차피
    balances 쪽에서 막아야 한다).

    잠금 순서는 orders(위 조건부 UPDATE) → balances → holdings → strategy_slots 이며,
    balances를 먼저 잡는 다른 경로들(orders.create_order 매수 검증, strategy_slots.toggle_slot,
    wallet 입출금)과 방향이 같아 교착이 생기지 않는다.
    """
    db.execute(select(Balance).where(Balance.user_id == user_id).with_for_update())


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
        cost_added = costs.calc_buy_amount(order.price, order.quantity, TRADING_FEE_RATE)
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
    if order.side == "buy":
        balance.krw_balance -= costs.calc_buy_amount(order.price, order.quantity, TRADING_FEE_RATE)
    else:
        balance.krw_balance += costs.calc_sell_amount(order.price, order.quantity, TRADING_FEE_RATE)
    balance.updated_at = datetime.now(timezone.utc)


def _format_quantity(quantity: Decimal) -> str:
    """코인 수량 표시 — 의미 없는 뒤쪽 0을 없앤다.

    `normalize()`만 쓰면 정수 수량이 지수 표기(1E+2)가 되므로 고정소수점 포맷을 함께 쓴다.
    """
    return f"{quantity.normalize():f}"


def _build_fill_message(order: Order, korean_name: str) -> str:
    """체결 알림 문구. 워커가 왜 팔았는지(손절/익절/신호)는 이 훅이 알 수 없으므로 추측하지 않고,
    실제로 아는 사실(체결 수량·가격·실현손익)만 적는다. 화면의 익절(파랑)/손절(빨강) 구분은
    realized_profit 부호로 판단한다 (07-auto-trading.md 3-C)."""
    quantity = _format_quantity(order.quantity)
    if order.side == "buy":
        return f"[{korean_name}] 자동매수 체결 — {quantity} 개 / {order.price:,.0f}원"

    profit = order.realized_profit if order.realized_profit is not None else Decimal(0)
    return f"[{korean_name}] 자동매도 체결 — {quantity} 개 / 실현손익 {profit:+,.0f}원"


def _apply_auto_trading_hook(db: Session, order: Order) -> None:
    """source='auto' 체결의 strategy_slots.state.position 갱신 + 알림 적재
    (09-execution-engine.md 3.2절 5단계).

    **이 함수가 state.position을 쓰는 유일한 주체다** (07-auto-trading.md 4장). 워커는 신호를
    내고 주문을 요청할 뿐 포지션을 직접 쓰지 않는다. 갱신은 fill_order의 트랜잭션 안에서
    일어나므로 체결·잔고·보유수량과 원자적으로 함께 확정된다 — 그래서 여기서 별도 세션을 열거나
    커밋하지 않는다.
    """
    if order.source != "auto" or order.strategy_slot_id is None:
        return

    slot = db.get(StrategySlot, order.strategy_slot_id)
    if slot is None:
        # 체결 직전에 슬롯이 삭제된 경우. 체결 자체는 유효하므로 되돌리지 않고, 인계할
        # 포지션 주체가 사라졌으니 그 코인은 수동 보유분으로 남는다 (07-auto-trading.md 4.2절).
        return

    position = slot_state.read_position(slot.state)
    if order.side == "buy":
        new_position = slot_state.apply_buy(
            position, order.price, order.quantity, TRADING_FEE_RATE, order.filled_at
        )
    else:
        new_position = slot_state.apply_sell(position, order.quantity)
    slot_state.write_position(db, slot.id, new_position)

    notification_type = "signal" if order.side == "buy" else "exit"
    settings = db.get(NotificationSetting, order.user_id)
    if not notifications_service.is_type_enabled(settings, notification_type):
        return

    coin = db.get(Coin, order.coin_symbol)
    db.add(
        Notification(
            user_id=order.user_id,
            type=notification_type,
            message=_build_fill_message(order, coin.korean_name if coin else order.coin_symbol),
            coin_symbol=order.coin_symbol,
            strategy_slot_id=slot.id,
            is_read=False,
            created_at=datetime.now(timezone.utc),
        )
    )


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

    # 체결을 선점한 뒤에 잠근다 — 경쟁에서 진 호출(rowcount==0)은 아무것도 갱신하지 않으므로
    # 잠글 필요도 없다.
    _lock_user_funds(db, order.user_id)

    if order.side == "sell":
        avg_buy_price_before = _apply_holdings(db, order)
        # 매수 수수료가 이미 avg_buy_price에 녹아 있어 이 한 줄로 왕복 수수료가 반영된다 (01-erd.md 3.2절)
        order.realized_profit = costs.calc_realized_profit(
            fill_price, order.quantity, avg_buy_price_before, TRADING_FEE_RATE
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
