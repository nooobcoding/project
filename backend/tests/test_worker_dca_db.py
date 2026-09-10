"""DCA 슬롯의 워커 동작 검증 (07 계획 Step 5).

트리거 판정 자체는 test_dca.py가 다루므로, 여기서는 워커가 DB와 맞물려 하는 일만 본다:
확정봉 게이트를 타지 않고 매 tick 도는지 / 체결 결과로 진행 상태를 갱신하는지 / 예산 상한이
실제 지출 기준으로 지켜지는지 / 목표 수익률 익절이 전량 매도 후 슬롯을 끄는지.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.database import session_scope
from app.models import Notification, Order, StrategySlot
from app.strategy_engine import worker
from tests.conftest import load_slot_state, requires_db

PRICE = Decimal("100000")
DCA_PARAMS = {
    "interval": "1d",
    "buy_period": "week",
    "amount_per_buy": 200000,
    "end_condition": "count",
    "max_count": 3,
}


def _orders(user_id: int) -> list[tuple[str, Decimal, Decimal]]:
    with session_scope() as db:
        return [
            (row.side, row.price, row.quantity)
            for row in db.execute(
                select(Order.side, Order.price, Order.quantity)
                .where(Order.user_id == user_id)
                .order_by(Order.id)
            )
        ]


def _dca(slot_id: int) -> dict:
    return load_slot_state(slot_id)["dca"]


def _is_active(slot_id: int) -> bool:
    with session_scope() as db:
        return db.get(StrategySlot, slot_id).is_active


@requires_db
def test_dca_buys_immediately_without_candles(make_slot, test_user, set_price):
    """DCA는 확정봉 게이트를 타지 않는다 — 캔들을 전혀 주지 않아도 첫 회차를 산다
    (07-auto-trading.md 4장 "DCA는 캔들이 아닌 시간 스케줄").

    캔들 조회를 monkeypatch하지 않는데도 동작한다는 점 자체가 검증 대상이다 — 지표형이라면
    합성 코인에 캔들이 없어 아무것도 못 했을 것이다.
    """
    slot_id = make_slot(
        strategy_type="dca", indicator=None, params=DCA_PARAMS, invest_amount=Decimal("1000000")
    )
    set_price(PRICE)

    worker.process_slot(slot_id)

    orders = _orders(test_user)
    assert [side for side, _, _ in orders] == ["buy"]

    dca = _dca(slot_id)
    assert dca["executed_count"] == 1
    assert Decimal(dca["last_buy_price"]) == PRICE
    assert dca["next_buy_at"] is not None


@requires_db
def test_dca_does_not_buy_twice_before_next_schedule(make_slot, test_user, set_price):
    """첫 매수 후 다음 예정 시각(1주 뒤)까지는 매 tick 돌아도 더 사지 않는다."""
    slot_id = make_slot(
        strategy_type="dca", indicator=None, params=DCA_PARAMS, invest_amount=Decimal("1000000")
    )
    set_price(PRICE)

    worker.process_slot(slot_id)
    worker.process_slot(slot_id)
    worker.process_slot(slot_id)

    assert len(_orders(test_user)) == 1


@requires_db
def test_dca_spent_amount_includes_fee(make_slot, test_user, set_price):
    """지출은 수수료까지 포함한 실제 체결액으로 쌓아야 예산 상한이 조금씩 새지 않는다
    (01-erd.md 3.2절 매수 체결액 = price × quantity × (1 + 수수료율))."""
    slot_id = make_slot(
        strategy_type="dca", indicator=None, params=DCA_PARAMS, invest_amount=Decimal("1000000")
    )
    set_price(PRICE)

    worker.process_slot(slot_id)

    _, fill_price, fill_quantity = _orders(test_user)[0]
    expected = fill_price * fill_quantity * Decimal("1.0005")
    assert Decimal(_dca(slot_id)["spent_amount"]) == expected


@requires_db
def test_dca_stops_at_max_count(make_slot, test_user, set_price):
    """총 횟수에 도달하면 예정 시각이 지나도 더 사지 않는다."""
    slot_id = make_slot(
        strategy_type="dca", indicator=None, params=DCA_PARAMS, invest_amount=Decimal("1000000")
    )
    set_price(PRICE)

    # 예정 시각을 과거로 되돌려가며 max_count(3)보다 많이 돌린다.
    for _ in range(5):
        worker.process_slot(slot_id)
        with session_scope() as db:
            slot = db.get(StrategySlot, slot_id)
            state = dict(slot.state)
            state["dca"] = {**state["dca"], "next_buy_at": "2020-01-01T00:00:00+00:00"}
            slot.state = state

    assert len(_orders(test_user)) == DCA_PARAMS["max_count"]


@requires_db
def test_dca_never_exceeds_invest_amount(make_slot, test_user, set_price):
    """예산 상한은 종료조건과 무관하게 항상 적용된다 (06-backtesting.md 2.4-1절).

    횟수는 넉넉히 두고 예산만 빠듯하게 잡아, 예산 쪽이 먼저 멈추는지 본다.
    """
    invest = Decimal("500000")  # 회당 200,000 → 2회까지만 가능(3회면 600,000 > 500,000)
    slot_id = make_slot(
        strategy_type="dca",
        indicator=None,
        params={**DCA_PARAMS, "max_count": 100},
        invest_amount=invest,
    )
    set_price(PRICE)

    for _ in range(5):
        worker.process_slot(slot_id)
        with session_scope() as db:
            slot = db.get(StrategySlot, slot_id)
            state = dict(slot.state)
            state["dca"] = {**state["dca"], "next_buy_at": "2020-01-01T00:00:00+00:00"}
            slot.state = state

    orders = _orders(test_user)
    assert len(orders) == 2
    spent = sum(price * quantity * Decimal("1.0005") for _, price, quantity in orders)
    assert spent <= invest


@requires_db
def test_dca_extra_buy_on_price_drop(make_slot, test_user, set_price):
    """추가매수 옵션 — 직전 매수가 대비 -X% 하락 시 정기 회차와 별개로 1회 더 산다."""
    slot_id = make_slot(
        strategy_type="dca",
        indicator=None,
        params={**DCA_PARAMS, "extra_buy_enabled": True, "extra_buy_drop_pct": 10},
        invest_amount=Decimal("1000000"),
    )
    set_price(PRICE)
    worker.process_slot(slot_id)  # 첫 정기 매수 (100,000원에 체결)
    assert len(_orders(test_user)) == 1

    set_price(Decimal("85000"))  # -15%
    worker.process_slot(slot_id)

    assert len(_orders(test_user)) == 2
    dca = _dca(slot_id)
    assert dca["executed_count"] == 2
    # 기준점이 방금 체결가로 내려갔으므로 같은 가격에서 또 발동하지 않는다("1회"의 의미).
    worker.process_slot(slot_id)
    assert len(_orders(test_user)) == 2


@requires_db
def test_dca_take_profit_liquidates_and_ends_strategy(make_slot, test_user, set_price):
    """목표 수익률 도달 시 전량 매도 후 전략을 종료(슬롯 OFF)한다 (06-backtesting.md 2.5절)."""
    slot_id = make_slot(
        strategy_type="dca",
        indicator=None,
        params=DCA_PARAMS,
        invest_amount=Decimal("1000000"),
        take_profit_pct=Decimal("10"),
    )
    set_price(PRICE)
    worker.process_slot(slot_id)
    assert _is_active(slot_id) is True

    set_price(Decimal("120000"))  # 평단(수수료 포함 100,050) 대비 약 +20%
    worker.process_slot(slot_id)

    assert [side for side, _, _ in _orders(test_user)] == ["buy", "sell"]
    assert "position" not in load_slot_state(slot_id)
    assert _is_active(slot_id) is False

    with session_scope() as db:
        messages = list(
            db.scalars(select(Notification.message).where(Notification.user_id == test_user))
        )
    assert any("자동매매를 종료" in message for message in messages)


@requires_db
def test_dca_has_no_stop_loss(make_slot, test_user, set_price):
    """DCA에는 손절이 없다 (06-backtesting.md 2.5절) — 값이 들어 있어도 청산되면 안 된다."""
    slot_id = make_slot(
        strategy_type="dca",
        indicator=None,
        params=DCA_PARAMS,
        invest_amount=Decimal("1000000"),
        stop_loss_pct=Decimal("5"),
    )
    set_price(PRICE)
    worker.process_slot(slot_id)

    set_price(Decimal("50000"))  # -50%
    worker.process_slot(slot_id)

    assert [side for side, _, _ in _orders(test_user)] == ["buy"]
    assert "position" in load_slot_state(slot_id)
    assert _is_active(slot_id) is True


@requires_db
def test_dca_skips_installment_when_balance_short(make_slot, test_user, set_price):
    """잔고 부족이면 이번 회차를 건너뛰고 다음 예정 시각으로 민다 — 밀지 않으면 매 tick마다
    같은 실패와 알림이 반복된다."""
    slot_id = make_slot(
        strategy_type="dca",
        indicator=None,
        params={**DCA_PARAMS, "amount_per_buy": 50000000},  # 시드머니 초과
        invest_amount=Decimal("100000000"),
    )
    set_price(PRICE)

    worker.process_slot(slot_id)

    assert _orders(test_user) == []
    dca = _dca(slot_id)
    assert dca["executed_count"] == 0
    assert dca["next_buy_at"] is not None  # 다음 회차로 밀렸다

    # 다음 tick에서는 예정 시각이 미래라 재시도하지 않는다(알림 폭주 방지).
    worker.process_slot(slot_id)
    with session_scope() as db:
        error_count = len(
            list(
                db.scalars(
                    select(Notification.id).where(
                        Notification.user_id == test_user, Notification.type == "error"
                    )
                )
            )
        )
    assert error_count == 1
