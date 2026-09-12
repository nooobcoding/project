"""runner.evaluate() 공유 진입점 검증 (07 계획 Step 1·4).

signals.py 자체의 판정 로직은 test_signals.py, 그리드 격자 산술은 test_grid.py에서 이미
검증하므로, 여기서는 runner가 SlotSpec → 전략별 평가로 라우팅하고 그 결과를 주문 의도
(TradeIntent)로 올바르게 옮기는지만 본다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.strategy_engine.runner import SlotSpec, evaluate

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)
INVEST = Decimal("1000000")


@dataclass
class _FakeCandle:
    """CandleLike 프로토콜(opened_at, close)만 만족하는 최소 더미 — ORM Candle에 의존하지 않는다."""

    opened_at: datetime
    close: Decimal


def _candles(*closes: float) -> list[_FakeCandle]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [_FakeCandle(opened_at=base, close=Decimal(str(c))) for c in closes]


def _spec(strategy_type: str, indicator: str | None, params: dict, state: dict | None = None) -> SlotSpec:
    return SlotSpec(
        strategy_type=strategy_type,
        indicator=indicator,
        params=params,
        invest_amount=INVEST,
        state=state or {},
    )


def _position(quantity: str, avg_price: str = "100000") -> dict:
    return {"position": {"quantity": quantity, "avg_price": avg_price, "entry_at": "2026-01-01T00:00:00+00:00"}}


# ── 지표형(추세추종/역추세) 라우팅 ────────────────────────────────────────────


def test_buy_signal_becomes_buy_intent_with_full_invest_amount():
    """추세추종/역추세의 1회 진입 금액은 invest_amount 전액이다 (06-backtesting.md 2.4-1절)."""
    slot = _spec("trend", "ma", {"short_period": 2, "long_period": 3})
    intents = evaluate(slot, _candles(10, 10, 10, 15), NOW)

    assert len(intents) == 1
    assert intents[0].side == "buy"
    assert intents[0].amount == INVEST
    assert intents[0].quantity is None


def test_buy_signal_is_ignored_while_position_open():
    """진입 후 청산까지 invest_amount를 재사용하지 않는다 — 이미 보유 중이면 매수 의도가 없다."""
    slot = _spec("trend", "ma", {"short_period": 2, "long_period": 3}, state=_position("0.5"))
    assert evaluate(slot, _candles(10, 10, 10, 15), NOW) == []


def test_sell_signal_becomes_sell_intent_for_whole_position():
    slot = _spec("trend", "ma", {"short_period": 2, "long_period": 3}, state=_position("0.5"))
    intents = evaluate(slot, _candles(20, 20, 20, 15), NOW)

    assert len(intents) == 1
    assert intents[0].side == "sell"
    assert intents[0].quantity == Decimal("0.5")


def test_sell_signal_without_position_produces_nothing():
    slot = _spec("trend", "ma", {"short_period": 2, "long_period": 3})
    assert evaluate(slot, _candles(20, 20, 20, 15), NOW) == []


def test_no_signal_produces_no_intent():
    """골든크로스 다음 봉(새 교차 없음) — test_signals.py의 중복 방지 케이스와 같은 데이터."""
    slot = _spec("trend", "ma", {"short_period": 2, "long_period": 3})
    assert evaluate(slot, _candles(10, 10, 10, 15, 16), NOW) == []


def test_returns_nothing_with_fewer_than_two_candles():
    """확정봉이 1개 이하면 어떤 지표도 크로스를 판정할 수 없다."""
    slot = _spec("trend", "rsi", {"period": 14})
    assert evaluate(slot, _candles(100), NOW) == []


def test_rejects_missing_indicator():
    """trend/counter_trend인데 indicator가 없으면 설계상 있을 수 없는 상태이므로 ValueError."""
    slot = _spec("trend", None, {})
    with pytest.raises(ValueError):
        evaluate(slot, _candles(10, 11), NOW)


# ── 그리드 라우팅 ──────────────────────────────────────────────────────────


def _grid_state(filled_flags: list[bool]) -> dict:
    """하한 100 / 상한 200 / 4칸 → 매수 라인 [100, 125, 150, 175]"""
    prices = ["100.00000000", "125.00000000", "150.00000000", "175.00000000"]
    return {
        "grid": {
            "lines": [
                {"price": price, "filled": filled, "quantity": "0.5" if filled else "0"}
                for price, filled in zip(prices, filled_flags)
            ]
        }
    }


GRID_PARAMS = {"lower_price": 100, "upper_price": 200, "grid_count": 4}


def test_grid_routes_to_line_evaluation():
    """가격이 150까지 내려오면 그 위 라인들(150·175)이 매수 대상이 된다."""
    slot = _spec("grid", None, GRID_PARAMS, state=_grid_state([False] * 4))
    intents = evaluate(slot, _candles(180, 150), NOW)

    assert [(i.side, i.grid_line_index) for i in intents] == [("buy", 2), ("buy", 3)]
    # 라인당 배분 = invest_amount / 격자 수
    assert all(i.amount == INVEST / 4 for i in intents)


def test_grid_without_lines_produces_nothing():
    """라인 초기화는 워커 책임이라, 아직 없으면 엔진은 아무것도 내지 않는다."""
    slot = _spec("grid", None, GRID_PARAMS)
    assert evaluate(slot, _candles(180, 150), NOW) == []


# ── DCA 라우팅 ────────────────────────────────────────────────────────────

DCA_PARAMS = {
    "interval": "1d",
    "buy_period": "week",
    "amount_per_buy": 100000,
    "end_condition": "count",
    "max_count": 10,
}


def test_dca_routes_to_scheduled_buy():
    """DCA는 캔들이 아니라 시간으로 트리거된다 — 캔들 없이도 예정 시각이면 매수가 나온다."""
    slot = _spec("dca", None, DCA_PARAMS)
    intents = evaluate(slot, [], NOW, current_price=Decimal("100"))

    assert len(intents) == 1
    assert intents[0].side == "buy"
    assert intents[0].amount == Decimal("100000")


def test_dca_uses_current_price_over_candle_close():
    """현재가를 명시하면 그것을 쓴다 — 워커는 실시간 시세를, 백테스팅은 봉 종가를 넣는다."""
    state = {
        "dca": {
            "executed_count": 1,
            "next_buy_at": "2099-01-01T00:00:00+00:00",  # 정기 매수는 아직 멀었다
            "last_buy_price": "100",
            "spent_amount": "100000",
        }
    }
    params = {**DCA_PARAMS, "extra_buy_enabled": True, "extra_buy_drop_pct": 10}
    slot = _spec("dca", None, params, state=state)

    # 봉 종가는 100(변동 없음)이지만 실시간 현재가가 -12%면 추가매수가 나와야 한다.
    assert evaluate(slot, _candles(100, 100), NOW) == []
    assert len(evaluate(slot, _candles(100, 100), NOW, current_price=Decimal("88"))) == 1
