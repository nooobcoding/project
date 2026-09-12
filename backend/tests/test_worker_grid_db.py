"""그리드 슬롯의 워커 동작 검증 (07 계획 Step 4).

순수 격자 산술은 test_grid.py가 다루므로, 여기서는 워커가 DB와 맞물려 하는 일만 본다:
라인 초기화 / 체결 결과로 라인 마킹 / 라인 합계가 배정액을 넘지 않는지 / 하한가 이탈 청산과
라인 리셋. 특히 **라인(워커 소유)과 state.position(체결 훅 소유)이 같은 체결을 근거로 갱신되어
서로 어긋나지 않는지**가 핵심이다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database import session_scope
from app.models import Order
from app.services import candles as candles_service
from app.strategy_engine import worker
from tests.conftest import load_slot_state, requires_db

CANDLE_START = datetime(2026, 9, 1, tzinfo=timezone.utc)

# 하한 100 / 상한 200 / 4칸 → 매수 라인 [100, 125, 150, 175], 라인당 배분 250,000원
GRID_PARAMS = {"interval": "1d", "lower_price": 100, "upper_price": 200, "grid_count": 4}
INVEST = Decimal("1000000")


class _Candle:
    def __init__(self, opened_at: datetime, close: Decimal) -> None:
        self.opened_at = opened_at
        self.close = close


def _candles(*closes) -> list[_Candle]:
    return [
        _Candle(CANDLE_START + timedelta(days=index), Decimal(str(close)))
        for index, close in enumerate(closes)
    ]


@pytest.fixture
def feed_candles(monkeypatch):
    def _feed(candles: list[_Candle]) -> None:
        monkeypatch.setattr(
            candles_service,
            "get_confirmed_candles",
            lambda db, symbol, interval, **kwargs: candles,
        )

    return _feed


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


def _lines(slot_id: int) -> list[dict]:
    return load_slot_state(slot_id)["grid"]["lines"]


@requires_db
def test_worker_initializes_grid_lines(make_slot, test_user, set_price, feed_candles):
    """라인 상태가 없으면 워커가 파라미터에서 만들어 저장한다 (라인은 워커 소유 키)."""
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("180"))
    feed_candles(_candles(190, 180))  # 아직 175까지 안 내려와 매수는 없다

    worker.process_slot(slot_id)

    lines = _lines(slot_id)
    assert [line["price"] for line in lines] == [
        "100.00000000",
        "125.00000000",
        "150.00000000",
        "175.00000000",
    ]
    assert all(line["filled"] is False for line in lines)
    assert _orders(test_user) == []


@requires_db
def test_worker_fills_lines_price_fell_through(make_slot, test_user, set_price, feed_candles):
    """확정봉 종가가 130이면 그 위 라인(150·175) 둘이 함께 체결된다."""
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("130"))
    feed_candles(_candles(190, 130))

    worker.process_slot(slot_id)

    orders = _orders(test_user)
    assert [side for side, _, _ in orders] == ["buy", "buy"]

    lines = _lines(slot_id)
    assert [line["filled"] for line in lines] == [False, False, True, True]


@requires_db
def test_filled_line_quantity_matches_actual_order(make_slot, test_user, set_price, feed_candles):
    """라인에 기록되는 수량은 "살 예정이던 양"이 아니라 실제 체결된 주문에서 되읽은 값이다 —
    이 덕분에 라인(워커 소유)과 state.position(체결 훅 소유)이 어긋나지 않는다."""
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("130"))
    feed_candles(_candles(190, 130))

    worker.process_slot(slot_id)

    orders = _orders(test_user)
    filled_quantities = sorted(Decimal(line["quantity"]) for line in _lines(slot_id) if line["filled"])
    assert filled_quantities == sorted(quantity for _, _, quantity in orders)

    # 라인 합계와 포지션 수량도 같은 체결에서 나왔으므로 일치해야 한다.
    position_quantity = Decimal(load_slot_state(slot_id)["position"]["quantity"])
    assert sum(filled_quantities) == position_quantity


@requires_db
def test_total_spend_stays_within_invest_amount(make_slot, test_user, set_price, feed_candles):
    """전 라인이 채워져도 총 지출이 배정액(invest_amount)을 넘지 않아야 한다
    (06-backtesting.md 2.4-1절 — invest_amount는 전체 격자 배분 상한)."""
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("100"))
    feed_candles(_candles(190, 100))  # 하한가까지 내려와 전 라인 체결

    worker.process_slot(slot_id)

    orders = _orders(test_user)
    assert len(orders) == 4
    spent = sum(price * quantity * Decimal("1.0005") for _, price, quantity in orders)
    assert spent <= INVEST


@requires_db
def test_worker_sells_line_when_price_reaches_target(make_slot, test_user, set_price, feed_candles):
    """라인 150(목표 175)을 든 상태에서 가격이 180으로 오르면 그 라인을 실현하고 비운다."""
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("160"))
    feed_candles(_candles(190, 160))
    worker.process_slot(slot_id)  # 라인 175 매수
    assert [line["filled"] for line in _lines(slot_id)] == [False, False, False, True]

    set_price(Decimal("201"))
    feed_candles(_candles(190, 160, 201))  # 라인 175의 목표는 200
    worker.process_slot(slot_id)

    assert [side for side, _, _ in _orders(test_user)] == ["buy", "sell"]
    assert [line["filled"] for line in _lines(slot_id)] == [False, False, False, False]


@requires_db
def test_grid_exit_liquidates_and_resets_lines(make_slot, test_user, set_price, feed_candles):
    """하한가 이탈 시 슬롯 보유분을 전량 청산하고 라인을 전부 비운다 (06-backtesting.md 2.5절).

    라인을 비우지 않으면 포지션은 사라졌는데 라인은 "채워짐"으로 남아, 가격이 회복돼도 다시
    매수되지 않고 있지도 않은 수량을 팔려고 하게 된다.
    """
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("130"))
    feed_candles(_candles(190, 130))
    worker.process_slot(slot_id)
    assert any(line["filled"] for line in _lines(slot_id))

    set_price(Decimal("90"))  # 하한가(100) 이탈
    worker.process_slot(slot_id)

    assert [side for side, _, _ in _orders(test_user)][-1] == "sell"
    assert "position" not in load_slot_state(slot_id)
    assert all(line["filled"] is False for line in _lines(slot_id))


@requires_db
def test_grid_does_not_buy_below_lower_bound(make_slot, test_user, set_price, feed_candles):
    """하한가 아래에서는 매수하지 않는다 — 이 방어가 없으면 이탈 순간 전 라인이 한꺼번에
    체결돼 배정액을 다 써버린다."""
    slot_id = make_slot(strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST)
    set_price(Decimal("90"))
    feed_candles(_candles(190, 90))

    worker.process_slot(slot_id)

    assert _orders(test_user) == []


@requires_db
def test_grid_ignores_stop_loss_and_take_profit_pct(make_slot, test_user, set_price, feed_candles):
    """그리드에는 %기반 손절·익절이 없다 — 값이 들어 있어도 이탈 손절만 동작해야 한다
    (06-backtesting.md 2.5절)."""
    slot_id = make_slot(
        strategy_type="grid",
        indicator=None,
        params=GRID_PARAMS,
        invest_amount=INVEST,
        stop_loss_pct=Decimal("1"),
        take_profit_pct=Decimal("1"),
    )
    set_price(Decimal("130"))
    feed_candles(_candles(190, 130))
    worker.process_slot(slot_id)
    buy_count = len(_orders(test_user))

    # 평단 대비 +1%를 훌쩍 넘겼지만 하한가 위이므로 청산되면 안 된다(라인 목표만 따른다).
    set_price(Decimal("140"))
    worker.process_slot(slot_id)

    assert len(_orders(test_user)) == buy_count
    assert "position" in load_slot_state(slot_id)
