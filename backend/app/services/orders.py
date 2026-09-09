"""03-manual-trading Control 계층 — 주문 생성/조회/취소.

create_order/cancel_order는 원시 인자만 받는다 (요청 객체를 받지 않음) — 07-auto-trading이
이 함수들을 내부 호출로 그대로 재사용하기 때문이다 (03-manual-trading.md 1장).
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.constants import TRADING_FEE_RATE
from app.models import Balance, Coin, Holding, Order, StrategySlot
from app.services import matcher, price_stream


class CoinNotFoundError(Exception):
    """존재하지 않거나 상장폐지(is_active=False)된 코인 심볼로 주문하려는 경우."""


class InvalidOrderInputError(Exception):
    """가격/수량이 0 이하인 경우 (03-manual-trading.md 4장)."""


class InsufficientBalanceError(Exception):
    """매수 시 가용 원화가 부족한 경우."""


class InsufficientHoldingError(Exception):
    """매도 시 가용 코인 수량이 부족한 경우."""

    def __init__(self, korean_name: str) -> None:
        self.korean_name = korean_name
        super().__init__(korean_name)


class PriceUnavailableError(Exception):
    """시장가 주문 시 시세 캐시에 아직 값이 없는 경우."""


class OrderNotFoundError(Exception):
    """존재하지 않거나 본인 소유가 아닌 주문을 조회/취소하려는 경우."""


class OrderNotCancelableError(Exception):
    """이미 체결·취소된 주문을 취소하려는 경우 (동시 체결과 경쟁해 패배한 경우 포함)."""


class CoinLockedByAutoTradingError(Exception):
    """해당 코인에 활성 자동매매 슬롯이 있어 수동 주문이 잠긴 경우 (07-auto-trading.md 5장 FR-M10)."""


def get_available_krw(db: Session, user_id: int) -> Decimal:
    """가용 원화 = balances.krw_balance − 미체결 매수 주문의 동결분 (01-erd.md 3.1절)."""
    balance = db.get(Balance, user_id)
    krw_balance = balance.krw_balance if balance is not None else Decimal(0)

    pending_buy_orders = db.scalars(
        select(Order).where(
            Order.user_id == user_id, Order.side == "buy", Order.status == "pending"
        )
    )
    locked = sum(
        (order.price * order.quantity * (1 + TRADING_FEE_RATE) for order in pending_buy_orders),
        Decimal(0),
    )
    return krw_balance - locked


def get_available_quantity(db: Session, user_id: int, coin_symbol: str) -> Decimal:
    """가용 코인 수량 = holdings.quantity − 미체결 매도 주문의 동결분 (01-erd.md 3.1절)."""
    holding = db.get(Holding, (user_id, coin_symbol))
    quantity = holding.quantity if holding is not None else Decimal(0)

    pending_sell_orders = db.scalars(
        select(Order).where(
            Order.user_id == user_id,
            Order.coin_symbol == coin_symbol,
            Order.side == "sell",
            Order.status == "pending",
        )
    )
    locked = sum((order.quantity for order in pending_sell_orders), Decimal(0))
    return quantity - locked


def create_order(
    db: Session,
    user_id: int,
    coin_symbol: str,
    side: str,
    order_type: str,
    quantity: Decimal,
    price: Decimal | None = None,
    trigger_price: Decimal | None = None,
    source: str = "manual",
    strategy_slot_id: int | None = None,
) -> Order:
    """주문을 생성한다. 시장가는 같은 트랜잭션 안에서 즉시 체결까지 수행한다
    (09-execution-engine.md 1장 — 시장가는 매칭 큐를 거치지 않는다).

    예약가(order_type='reserved')는 감시가격(trigger_price) 도달 시 order_type이
    'limit'으로 승격될 뿐, 자체 체결 경로는 갖지 않는다 (services/matcher.py 참고).

    source="auto"·strategy_slot_id는 07-auto-trading 워커가 이 함수를 내부 호출로 재사용할
    때 넘긴다 (03-manual-trading.md 1장). source="manual"일 때는 해당 코인에 활성 자동매매
    슬롯이 있으면 거부한다 — 자동매매가 그 코인의 포지션을 관리하는 도중 수동 주문이 끼어들면
    슬롯의 state.position과 실제 holdings가 어긋날 수 있기 때문이다(07-auto-trading.md 5장
    FR-M10). 미체결 주문 취소(cancel_order)는 이 잠금과 무관하게 항상 허용한다.
    """
    coin = db.get(Coin, coin_symbol)
    if coin is None or not coin.is_active:
        raise CoinNotFoundError()

    if quantity <= 0 or (order_type in ("limit", "reserved") and (price is None or price <= 0)):
        raise InvalidOrderInputError()
    if order_type == "reserved" and (trigger_price is None or trigger_price <= 0):
        raise InvalidOrderInputError()

    if source == "manual":
        locked = db.scalar(
            select(StrategySlot).where(
                StrategySlot.user_id == user_id,
                StrategySlot.coin_symbol == coin_symbol,
                StrategySlot.is_active,
            )
        )
        if locked is not None:
            raise CoinLockedByAutoTradingError()

    trigger_direction: str | None = None
    if order_type == "market":
        cached = price_stream.get_cached_price(coin_symbol)
        if cached is None:
            raise PriceUnavailableError()
        effective_price = Decimal(str(cached["trade_price"]))
    elif order_type == "reserved":
        cached = price_stream.get_cached_price(coin_symbol)
        if cached is None:
            raise PriceUnavailableError()
        current_price = Decimal(str(cached["trade_price"]))
        # 주문 생성 시점의 현재가 대비 감시가격 위치로 방향을 1회 확정한다 (01-erd.md 참고).
        # 같으면 상승/하락 어느 쪽을 기다리는지 모호하므로 거부한다.
        if trigger_price > current_price:
            trigger_direction = "rising"
        elif trigger_price < current_price:
            trigger_direction = "falling"
        else:
            raise InvalidOrderInputError()
        effective_price = price
    else:
        effective_price = price

    if side == "buy":
        # 가용잔고 조회(get_available_krw)와 주문 insert 사이에 틈이 있으면, 동시에 들어온
        # 두 주문이 서로 상대방의 동결분을 못 본 채(stale read) 둘 다 통과해 잔고를 초과할
        # 수 있다. balances 행을 잠가(FOR UPDATE) 같은 유저의 동시 매수 검증을 직렬화한다 —
        # 체결 쪽은 이미 fill_order의 조건부 UPDATE로 안전하지만, 이 생성 단계는 그렇지
        # 않았다. 잠금은 이 트랜잭션이 커밋/롤백될 때(바로 아래 db.commit()) 풀린다.
        db.execute(select(Balance).where(Balance.user_id == user_id).with_for_update())
        required = effective_price * quantity * (1 + TRADING_FEE_RATE)
        if required > get_available_krw(db, user_id):
            raise InsufficientBalanceError()
    else:
        # 매도도 동일한 이유로 holdings 행을 잠가 동시 매도 검증을 직렬화한다.
        db.execute(
            select(Holding)
            .where(Holding.user_id == user_id, Holding.coin_symbol == coin_symbol)
            .with_for_update()
        )
        if quantity > get_available_quantity(db, user_id, coin_symbol):
            raise InsufficientHoldingError(coin.korean_name)

    order = Order(
        user_id=user_id,
        coin_symbol=coin_symbol,
        side=side,
        order_type=order_type,
        price=effective_price,
        quantity=quantity,
        status="pending",
        source=source,
        fee=Decimal(0),
        trigger_price=trigger_price if order_type == "reserved" else None,
        trigger_direction=trigger_direction,
        strategy_slot_id=strategy_slot_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    if order_type == "market":
        matcher.fill_order(db, order, fill_price=effective_price)
        db.refresh(order)

    return order


def cancel_order(db: Session, user_id: int, order_id: int) -> None:
    """미체결 주문을 취소한다. 체결 엔진과 동일한 조건부 UPDATE로 경쟁을 방지한다
    (09-execution-engine.md 3.3절)."""
    order = db.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise OrderNotFoundError()

    result = db.execute(
        update(Order)
        .where(Order.id == order_id, Order.status == "pending")
        .values(status="canceled")
    )
    db.commit()
    if result.rowcount == 0:
        raise OrderNotCancelableError()


def list_pending_orders(db: Session, user_id: int) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .where(Order.user_id == user_id, Order.status == "pending")
            .order_by(Order.created_at.desc())
        )
    )


def list_order_history(
    db: Session, user_id: int, coin_symbol: str | None = None, limit: int = 50
) -> list[Order]:
    """체결·취소된 최근 주문 목록 (거래내역 탭)."""
    conditions = [Order.user_id == user_id, Order.status.in_(["filled", "canceled"])]
    if coin_symbol is not None:
        conditions.append(Order.coin_symbol == coin_symbol)
    return list(
        db.scalars(
            select(Order).where(*conditions).order_by(Order.created_at.desc()).limit(limit)
        )
    )
