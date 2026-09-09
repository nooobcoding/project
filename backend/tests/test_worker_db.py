"""워커 tick의 DB 연동 동작 검증 (07 계획 Step 2B).

실제 1분봉을 기다리지 않고 합성 확정봉과 가짜 시세를 주입해 `process_slot`을 직접 호출한다.
가장 중요한 검증은 **같은 확정봉으로 tick이 여러 번 돌아도 주문이 한 번만 나가는지**다 —
워커 tick(10초)이 봉 주기(최소 1분)보다 훨씬 촘촘해 같은 봉을 반복해서 보기 때문에, 이 방어가
없으면 봉 하나당 주문이 6번 이상 나간다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.models import Notification, Order
from app.services import candles as candles_service
from app.services.slot_state import write_position
from app.strategy_engine import worker
from tests.conftest import load_slot_state, requires_db

PRICE = Decimal("100000")
CANDLE_START = datetime(2026, 9, 1, tzinfo=timezone.utc)

# MA(2) vs MA(3) 골든크로스가 마지막 봉에서 발생하는 종가열 (tests/test_signals.py에서 검증한 것과 동일).
BUY_SIGNAL_CLOSES = [10, 10, 10, 15]
MA_PARAMS = {"interval": "1d", "short_period": 2, "long_period": 3}


class _Candle:
    """CandleLike(opened_at/close)만 만족하는 합성 확정봉."""

    def __init__(self, opened_at: datetime, close: Decimal) -> None:
        self.opened_at = opened_at
        self.close = close


def _candles(closes, *, start: datetime = CANDLE_START) -> list[_Candle]:
    return [
        _Candle(start + timedelta(days=index), Decimal(str(close)))
        for index, close in enumerate(closes)
    ]


@pytest.fixture
def feed_candles(monkeypatch):
    """워커가 읽는 확정봉을 통제한다. 실제 Upbit 호출·캔들 캐시를 타지 않게 한다."""

    def _feed(candles: list[_Candle]) -> None:
        monkeypatch.setattr(
            candles_service, "get_confirmed_candles", lambda db, symbol, interval: candles
        )

    return _feed


def _count_orders(user_id: int) -> int:
    with session_scope() as db:
        return db.scalar(select(func.count()).select_from(Order).where(Order.user_id == user_id))


@requires_db
def test_worker_buys_on_signal(make_slot, test_user, test_coin, set_price, feed_candles):
    """골든크로스 확정봉이 들어오면 시장가 매수가 나가고 포지션이 열린다."""
    slot_id = make_slot(params=MA_PARAMS)
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))

    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 1
    with session_scope() as db:
        row = db.execute(
            select(Order.side, Order.order_type, Order.source, Order.strategy_slot_id)
            .where(Order.user_id == test_user)
        ).one()
    # 워커 주문은 항상 시장가다 (07-auto-trading.md 4.1절).
    assert row == ("buy", "market", "auto", slot_id)
    assert "position" in load_slot_state(slot_id)


@requires_db
def test_worker_places_one_order_per_candle(make_slot, test_user, test_coin, set_price, feed_candles):
    """같은 확정봉으로 tick이 두 번 돌아도 주문은 한 번만 나가야 한다."""
    slot_id = make_slot(params=MA_PARAMS)
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))

    worker.process_slot(slot_id)
    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 1


@requires_db
def test_worker_skips_same_candle_even_without_position(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """확정봉 선점만으로도 중복 주문이 막혀야 한다.

    첫 tick 뒤 포지션을 강제로 지워 "이미 포지션이 있으니 재진입 안 함" 쪽 방어를 무력화한 뒤
    다시 tick을 돌린다. 그래도 주문이 늘지 않아야 `claim_candle`이 실제로 일하고 있는 것이다 —
    두 방어가 겹쳐 있어 이걸 분리하지 않으면 선점 로직이 깨져도 테스트가 통과해 버린다.
    """
    slot_id = make_slot(params=MA_PARAMS)
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))

    worker.process_slot(slot_id)
    with session_scope() as db:
        write_position(db, slot_id, None)

    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 1


@requires_db
def test_worker_evaluates_again_on_new_candle(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """새 확정봉이 생기면 다시 평가한다 — 선점이 영구 차단이 되어선 안 된다."""
    slot_id = make_slot(params=MA_PARAMS)
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))
    worker.process_slot(slot_id)

    # 포지션을 비우고(청산된 셈) 골든크로스가 다시 발생하는 새 봉을 공급한다.
    with session_scope() as db:
        write_position(db, slot_id, None)
    feed_candles(_candles(BUY_SIGNAL_CLOSES + [10, 10, 15]))

    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 2


@requires_db
def test_worker_does_not_rebuy_while_position_open(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """추세추종/역추세의 invest_amount는 1회 진입 금액이라 청산 전까지 재진입하지 않는다
    (06-backtesting.md 2.4-1절)."""
    slot_id = make_slot(params=MA_PARAMS)
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))
    worker.process_slot(slot_id)

    # 포지션은 그대로 둔 채 새 골든크로스 봉만 공급한다.
    feed_candles(_candles(BUY_SIGNAL_CLOSES + [10, 10, 15]))
    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 1


@requires_db
def test_worker_takes_profit_on_price_rise(make_slot, test_user, test_coin, set_price, feed_candles):
    """익절은 확정봉을 기다리지 않고 매 tick 실시간 현재가로 판정한다 (07 4장)."""
    slot_id = make_slot(params=MA_PARAMS, take_profit_pct=Decimal("5"))
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))
    worker.process_slot(slot_id)
    assert _count_orders(test_user) == 1

    # 평단(100,050) 대비 +10% — 새 확정봉 없이도 청산되어야 한다.
    set_price(Decimal("110055"))
    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 2
    with session_scope() as db:
        sides = list(
            db.scalars(select(Order.side).where(Order.user_id == test_user).order_by(Order.id))
        )
    assert sides == ["buy", "sell"]
    assert "position" not in load_slot_state(slot_id)


@requires_db
def test_worker_stops_loss_on_price_drop(make_slot, test_user, test_coin, set_price, feed_candles):
    slot_id = make_slot(params=MA_PARAMS, stop_loss_pct=Decimal("5"))
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))
    worker.process_slot(slot_id)

    set_price(Decimal("90000"))  # 평단 대비 약 -10%
    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 2
    assert "position" not in load_slot_state(slot_id)


@requires_db
def test_worker_does_not_sell_manual_holdings(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """청산 수량은 슬롯이 산 몫으로 상한을 건다 — 수동 보유분은 남아야 한다 (07 4.2절)."""
    slot_id = make_slot(params=MA_PARAMS, take_profit_pct=Decimal("5"))
    set_price(PRICE)

    # 수동 보유분 5개를 먼저 만든다 (슬롯 OFF 상태에서만 수동 주문이 가능하므로 잠시 내린다).
    with session_scope() as db:
        from app.models import StrategySlot
        from app.services.orders import create_order

        db.get(StrategySlot, slot_id).is_active = False
        db.flush()
        create_order(
            db,
            user_id=test_user,
            coin_symbol=test_coin,
            side="buy",
            order_type="market",
            quantity=Decimal("5"),
            source="manual",
        )
        db.get(StrategySlot, slot_id).is_active = True

    feed_candles(_candles(BUY_SIGNAL_CLOSES))
    worker.process_slot(slot_id)  # 슬롯이 자기 몫 매수
    slot_quantity = Decimal(load_slot_state(slot_id)["position"]["quantity"])

    set_price(Decimal("110055"))  # 익절 발동
    worker.process_slot(slot_id)

    with session_scope() as db:
        sold = db.scalar(
            select(func.sum(Order.quantity)).where(
                Order.user_id == test_user, Order.side == "sell"
            )
        )
    assert sold == slot_quantity  # 수동 보유 5개는 건드리지 않았다


@requires_db
def test_worker_notifies_and_keeps_slot_on_when_balance_short(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """실행 시점 잔고 부족은 그 매수만 건너뛰고 슬롯은 ON을 유지한다 (07 2.1절·6장)."""
    slot_id = make_slot(params=MA_PARAMS, invest_amount=Decimal("50000000"))  # 시드머니 초과
    set_price(PRICE)
    feed_candles(_candles(BUY_SIGNAL_CLOSES))

    worker.process_slot(slot_id)

    assert _count_orders(test_user) == 0
    with session_scope() as db:
        rows = list(
            db.execute(
                select(Notification.type, Notification.message).where(
                    Notification.user_id == test_user
                )
            )
        )
    assert len(rows) == 1
    assert rows[0][0] == "error"
    assert "가용 잔고 부족으로 스킵" in rows[0][1]

    with session_scope() as db:
        from app.models import StrategySlot

        assert db.get(StrategySlot, slot_id).is_active is True
