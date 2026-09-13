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


# --- 실제 가용 수량이 라인 수량보다 적을 때 ---------------------------------
#
# 슬롯이 팔려는 양보다 실제로 팔 수 있는 양이 적을 수 있다 — 매도 수량은
# `min(요청, 슬롯 포지션, 가용 코인 수량)`으로 상한이 걸리고, 같은 코인에 수동 미체결 매도가
# 남아 있으면(자동매매를 켜기 전에 낸 주문은 그대로 살아 있다) 가용 수량이 그만큼 준다.
#
# **이때 라인을 통째로 비우면 안 된다.** `state.position`은 실제 체결 수량만큼만 줄어드는데
# 라인은 전량이 나간 것으로 기록되므로 (a) `Σ lines == position` 불변식이 깨지고
# (b) 그 라인이 다시 매수 대상이 되어 이미 들고 있는 몫을 또 사게 된다(배정액 초과).


def _add_pending_manual_sell(user_id: int, symbol: str, quantity: Decimal) -> None:
    """자동매매를 켜기 전에 낸 수동 지정가 매도가 아직 미체결로 남아 있는 상태.

    `create_order`는 활성 슬롯이 있는 코인의 수동 주문을 막으므로(FR-M10) 행을 직접 넣는다 —
    잠금은 **새 주문만** 막고 이미 낸 미체결 주문은 그대로 살아 있기 때문에, 이건 실제로
    일어나는 상태다 (docs/features/07-auto-trading.md 5장).
    """
    with session_scope() as db:
        db.add(
            Order(
                user_id=user_id,
                coin_symbol=symbol,
                side="sell",
                order_type="limit",
                price=Decimal("100000"),  # 체결되지 않을 만큼 높게 — 미체결로만 남는다
                quantity=quantity,
                status="pending",
                source="manual",
                fee=Decimal("0"),
                created_at=datetime.now(timezone.utc),
            )
        )


def _position_quantity(slot_id: int) -> Decimal:
    position = load_slot_state(slot_id).get("position")
    return Decimal(position["quantity"]) if position else Decimal(0)


def _lines_quantity(slot_id: int) -> Decimal:
    return sum(
        (Decimal(line["quantity"]) for line in _lines(slot_id) if line["filled"]),
        start=Decimal(0),
    )


@requires_db
def test_partial_line_sell_keeps_the_remainder_on_the_line(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """덜 팔렸으면 판 만큼만 라인에서 깎는다 — 라인을 통째로 비우지 않는다."""
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST
    )
    set_price(Decimal("160"))
    feed_candles(_candles(190, 160))
    worker.process_slot(slot_id)  # 라인 175 매수
    bought = _position_quantity(slot_id)
    assert bought > 0

    # 보유분의 절반을 수동 미체결 매도가 묶어 둔다 → 가용 수량이 절반으로 준다.
    locked = (bought / 2).quantize(Decimal("0.00000001"))
    _add_pending_manual_sell(test_user, test_coin, locked)

    set_price(Decimal("201"))
    feed_candles(_candles(190, 160, 201))  # 라인 175의 목표(200) 도달
    worker.process_slot(slot_id)

    remaining_line = [line for line in _lines(slot_id) if line["filled"]]
    assert remaining_line, "덜 팔렸는데 라인이 통째로 비워졌다 — 그 라인을 또 사게 된다"
    assert _lines_quantity(slot_id) == _position_quantity(slot_id)


@requires_db
def test_partial_breakout_liquidation_keeps_lines_consistent(
    make_slot, test_user, test_coin, set_price, feed_candles
):
    """하한가 이탈 청산도 덜 팔릴 수 있다 — 그때 라인을 전부 비우면 같은 사고가 난다."""
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST
    )
    set_price(Decimal("130"))
    feed_candles(_candles(190, 130))
    worker.process_slot(slot_id)
    bought = _position_quantity(slot_id)
    assert bought > 0

    locked = (bought / 2).quantize(Decimal("0.00000001"))
    _add_pending_manual_sell(test_user, test_coin, locked)

    set_price(Decimal("90"))  # 하한가(100) 이탈
    worker.process_slot(slot_id)

    assert _position_quantity(slot_id) > 0  # 다 못 팔았으므로 포지션이 남는다
    assert _lines_quantity(slot_id) == _position_quantity(slot_id)


@requires_db
def test_full_sell_still_empties_the_line(make_slot, test_user, set_price, feed_candles):
    """전량 팔렸으면 지금까지대로 라인을 비운다 (수정이 정상 경로를 바꾸지 않는다)."""
    slot_id = make_slot(
        strategy_type="grid", indicator=None, params=GRID_PARAMS, invest_amount=INVEST
    )
    set_price(Decimal("160"))
    feed_candles(_candles(190, 160))
    worker.process_slot(slot_id)

    set_price(Decimal("201"))
    feed_candles(_candles(190, 160, 201))
    worker.process_slot(slot_id)

    assert all(line["filled"] is False for line in _lines(slot_id))
    assert _lines_quantity(slot_id) == _position_quantity(slot_id) == Decimal(0)
