"""runner.evaluate() 공유 진입점 검증 (07 계획 Step 1).

signals.py 자체의 판정 로직은 test_signals.py에서 이미 검증했으므로, 여기서는 runner가
SlotSpec → signal_func 라우팅과 캔들 부족·미지원 조합 예외 처리를 올바르게 수행하는지만 본다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.strategy_engine.runner import SlotSpec, evaluate


@dataclass
class _FakeCandle:
    """CandleLike 프로토콜(opened_at, close)만 만족하는 최소 더미 — ORM Candle에 의존하지 않는다."""

    opened_at: datetime
    close: Decimal


def _candles(*closes: float) -> list[_FakeCandle]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [_FakeCandle(opened_at=base, close=Decimal(str(c))) for c in closes]


def test_evaluate_routes_trend_ma_to_correct_signal_func():
    """test_signals.py의 골든크로스 케이스와 동일한 데이터로, runner를 거쳐도 같은 결과가 나오는지 확인."""
    slot = SlotSpec(
        strategy_type="trend",
        indicator="ma",
        params={"short_period": 2, "long_period": 3},
    )
    signal = evaluate(slot, _candles(10, 10, 10, 15), now=datetime.now(timezone.utc))
    assert signal == "buy"


def test_evaluate_returns_none_with_fewer_than_two_candles():
    """확정봉이 1개 이하면 어떤 지표도 크로스를 판정할 수 없으므로 None을 반환해야 한다."""
    slot = SlotSpec(strategy_type="trend", indicator="rsi", params={"period": 14})
    signal = evaluate(slot, _candles(100), now=datetime.now(timezone.utc))
    assert signal is None


def test_evaluate_grid_not_implemented_yet():
    """그리드는 07 Step 4에서 구현 — 지금은 명시적으로 NotImplementedError여야 한다."""
    slot = SlotSpec(strategy_type="grid", indicator=None, params={})
    with pytest.raises(NotImplementedError):
        evaluate(slot, _candles(10, 11), now=datetime.now(timezone.utc))


def test_evaluate_dca_not_implemented_yet():
    """DCA는 07 Step 5에서 구현 — 지금은 명시적으로 NotImplementedError여야 한다."""
    slot = SlotSpec(strategy_type="dca", indicator=None, params={})
    with pytest.raises(NotImplementedError):
        evaluate(slot, _candles(10, 11), now=datetime.now(timezone.utc))


def test_evaluate_rejects_missing_indicator():
    """trend/counter_trend인데 indicator가 없으면 설계상 있을 수 없는 상태이므로 ValueError."""
    slot = SlotSpec(strategy_type="trend", indicator=None, params={})
    with pytest.raises(ValueError):
        evaluate(slot, _candles(10, 11), now=datetime.now(timezone.utc))
