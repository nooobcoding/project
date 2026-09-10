"""슬롯 재ON 시 phantom position 보정 검증 (08 Phase B). 실제 postgres에 붙는다.

슬롯이 OFF인 사이에는 그 코인의 수동매매 잠금이 풀리므로 사용자가 슬롯 보유분까지 팔 수 있다.
그 상태로 다시 켜면 슬롯이 있지도 않은 포지션을 들고 있다고 믿어 재진입도 청산도 못 하게 되므로,
ON 시점에 실제 holdings와 대조해 낮춰야 한다 (07-auto-trading.md 4.2절).
"""

from decimal import Decimal

import pytest

from app.database import session_scope
from app.models import Holding
from app.services import strategy_slots as slots_service

from .conftest import TEST_COIN_SYMBOL, load_slot_state, requires_db

pytestmark = requires_db

# 슬롯이 10개를 들고 있다고 기록된 상태에서 시작한다.
POSITION = {"quantity": "10", "avg_price": "1000", "entry_at": "2026-09-01T00:00:00+00:00"}


def _set_holding(user_id: int, quantity: Decimal) -> None:
    with session_scope() as db:
        holding = db.get(Holding, (user_id, TEST_COIN_SYMBOL))
        if holding is None:
            holding = Holding(user_id=user_id, coin_symbol=TEST_COIN_SYMBOL)
            db.add(holding)
        holding.quantity = quantity
        holding.avg_buy_price = Decimal("1000")


def _turn_on(user_id: int, slot_id: int) -> None:
    with session_scope() as db:
        slots_service.toggle_slot(db, user_id, slot_id, True)


def test_full_manual_sell_clears_position_on_reactivation(test_user, make_slot):
    """OFF 중 전량 매도했으면 position 키 자체가 사라져야 슬롯이 다시 진입할 수 있다."""
    slot_id = make_slot(is_active=False, state={"position": POSITION})
    _set_holding(test_user, Decimal("0"))

    _turn_on(test_user, slot_id)

    assert "position" not in load_slot_state(slot_id)


def test_partial_manual_sell_lowers_position_on_reactivation(test_user, make_slot):
    slot_id = make_slot(is_active=False, state={"position": POSITION})
    _set_holding(test_user, Decimal("4"))

    _turn_on(test_user, slot_id)

    position = load_slot_state(slot_id)["position"]
    assert Decimal(position["quantity"]) == Decimal("4")
    # 평단·진입시각은 보정 대상이 아니다 — 취득원가는 남은 수량에 그대로 따라간다.
    assert position["avg_price"] == POSITION["avg_price"]
    assert position["entry_at"] == POSITION["entry_at"]


def test_manual_buy_does_not_raise_position(test_user, make_slot):
    """OFF 중 수동 매수로 보유량이 늘어도 슬롯 몫은 그대로다 — 수동 보유분은 관리 대상이 아니다."""
    slot_id = make_slot(is_active=False, state={"position": POSITION})
    _set_holding(test_user, Decimal("15"))

    _turn_on(test_user, slot_id)

    assert Decimal(load_slot_state(slot_id)["position"]["quantity"]) == Decimal("10")


def test_other_state_keys_survive_reconciliation(test_user, make_slot):
    """보정은 position만 건드린다 — 워커 소유 키(그리드 라인 등)를 함께 날리면 안 된다."""
    lines = [{"price": "900", "filled": True, "quantity": "10"}]
    slot_id = make_slot(
        is_active=False,
        state={"position": POSITION, "grid": {"lines": lines}, "last_evaluated_candle_at": "2026-09-01T00:00:00+00:00"},
    )
    _set_holding(test_user, Decimal("0"))

    _turn_on(test_user, slot_id)

    state = load_slot_state(slot_id)
    assert "position" not in state
    assert state["grid"]["lines"] == lines
    assert state["last_evaluated_candle_at"] == "2026-09-01T00:00:00+00:00"


def test_rejected_activation_leaves_position_untouched(test_user, make_slot):
    """ON이 거부되면 보정도 남기지 않는다 — 검증 통과 후에만 쓰기 때문이다."""
    slot_id = make_slot(
        is_active=False, state={"position": POSITION}, invest_amount=Decimal("99000000")
    )
    _set_holding(test_user, Decimal("0"))

    with pytest.raises(slots_service.InsufficientAllocatableBalanceError):
        _turn_on(test_user, slot_id)

    assert load_slot_state(slot_id)["position"] == POSITION


def test_slot_without_position_activates_normally(test_user, make_slot):
    slot_id = make_slot(is_active=False, state={})

    _turn_on(test_user, slot_id)

    assert load_slot_state(slot_id) == {}
