"""청산 판정 검증 (06 계획 A-1). DB·네트워크 없이 돈다.

돈이 직접 걸리는 판정이라 경계값을 촘촘히 본다. 원래 워커의 `decide_exit`이 하던 검증(추세추종
손절·익절 경계)을 그대로 이어받고, 워커 private였던 그리드 이탈·DCA 익절 규칙까지 여기서 함께
본다 — 백테스팅이 같은 함수를 쓰게 되므로 전략유형별 규칙이 한 자리에서 검증돼야 한다.
"""

from decimal import Decimal

import pytest

from app.strategy_engine import exits
from app.strategy_engine.runner import SlotSpec

GRID_PARAMS = {"lower_price": "100", "upper_price": "200", "grid_count": 4}


def _position(quantity: str = "1", avg_price: str = "100000") -> dict[str, str]:
    return {"quantity": quantity, "avg_price": avg_price, "entry_at": "2026-01-01T00:00:00+00:00"}


def _spec(strategy_type: str = "trend", **kwargs) -> SlotSpec:
    return SlotSpec(
        strategy_type=strategy_type,
        indicator="ma" if strategy_type in ("trend", "counter_trend") else None,
        params=kwargs.pop("params", {}),
        invest_amount=Decimal("1000000"),
        **kwargs,
    )


# ── 추세추종/역추세 — 진입가 대비 ±X% ──────────────────────────────────────


@pytest.mark.parametrize("strategy_type", ["trend", "counter_trend"])
def test_take_profit_on_reaching_threshold(strategy_type):
    """진입가 100,000 / 익절 5% → 105,000 도달 시 익절 (06-backtesting.md 2.5절)."""
    intent = exits.decide_exit(
        _spec(strategy_type, take_profit_pct=Decimal("5")), _position(), Decimal("105000")
    )

    assert intent is not None
    assert intent.reason == exits.TAKE_PROFIT
    assert intent.side == "sell"
    assert intent.quantity == Decimal("1")


def test_stop_loss_on_reaching_threshold():
    """손절 기준은 양수로 저장되고 -X% 도달 시 발동한다."""
    intent = exits.decide_exit(
        _spec(stop_loss_pct=Decimal("5")), _position(), Decimal("95000")
    )

    assert intent is not None and intent.reason == exits.STOP_LOSS


def test_none_within_band():
    spec = _spec(stop_loss_pct=Decimal("5"), take_profit_pct=Decimal("5"))

    assert exits.decide_exit(spec, _position(), Decimal("102000")) is None


def test_ignores_unset_thresholds():
    """손절·익절을 설정하지 않은 슬롯은 아무리 움직여도 청산하지 않는다."""
    spec = _spec()

    assert exits.decide_exit(spec, _position(), Decimal("10")) is None
    assert exits.decide_exit(spec, _position(), Decimal("100000000")) is None


def test_take_profit_wins_when_both_would_trigger():
    """설정이 이상해 둘 다 걸리는 경우(익절≤0 등)에도 판정이 흔들리지 않게 익절을 먼저 본다."""
    spec = _spec(stop_loss_pct=Decimal("-100"), take_profit_pct=Decimal("5"))

    intent = exits.decide_exit(spec, _position(), Decimal("105000"))

    assert intent is not None and intent.reason == exits.TAKE_PROFIT


def test_guards_zero_average_price():
    """평단 0(포지션이 비정상)일 때 0으로 나누지 않는다."""
    spec = _spec(stop_loss_pct=Decimal("5"), take_profit_pct=Decimal("5"))

    assert exits.decide_exit(spec, _position(avg_price="0"), Decimal("100")) is None


# ── 포지션이 없을 때 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("position", [None, {}, {"quantity": "0", "avg_price": "100000"}])
def test_no_position_never_exits(position):
    """팔 것이 없으면 어떤 전략유형도 청산 의도를 내지 않는다."""
    spec = _spec(take_profit_pct=Decimal("1"))

    assert exits.decide_exit(spec, position, Decimal("999999999")) is None


# ── 그리드 — 하한가 이탈 손절만, 익절 없음 ─────────────────────────────────


def test_grid_exits_below_lower_bound():
    spec = _spec("grid", params=GRID_PARAMS)

    intent = exits.decide_exit(spec, _position(avg_price="150"), Decimal("99"))

    assert intent is not None and intent.reason == exits.GRID_BREAKOUT


def test_grid_holds_at_lower_bound():
    """하한가 "이탈"이므로 하한가 정확히 그 값은 아직 범위 안이다 (grid.evaluate와 같은 경계)."""
    spec = _spec("grid", params=GRID_PARAMS)

    assert exits.decide_exit(spec, _position(avg_price="150"), Decimal("100")) is None


def test_grid_has_no_take_profit():
    """라인별로 개별 실현하므로 그리드에는 익절 청산이 없다 — 값이 설정돼 있어도 무시한다."""
    spec = _spec("grid", params=GRID_PARAMS, take_profit_pct=Decimal("1"))

    assert exits.decide_exit(spec, _position(avg_price="150"), Decimal("100000")) is None


# ── DCA — 목표 수익률 익절만, 손절 없음 ────────────────────────────────────


def test_dca_take_profit_on_reaching_target():
    spec = _spec("dca", take_profit_pct=Decimal("10"))

    intent = exits.decide_exit(spec, _position(), Decimal("110000"))

    assert intent is not None and intent.reason == exits.DCA_TAKE_PROFIT


def test_dca_holds_below_target():
    spec = _spec("dca", take_profit_pct=Decimal("10"))

    assert exits.decide_exit(spec, _position(), Decimal("109999")) is None


def test_dca_has_no_stop_loss():
    """하락 구간에 계속 사 모으는 것이 전제이므로 DCA는 손절하지 않는다."""
    spec = _spec("dca", stop_loss_pct=Decimal("5"), take_profit_pct=Decimal("10"))

    assert exits.decide_exit(spec, _position(), Decimal("1")) is None
