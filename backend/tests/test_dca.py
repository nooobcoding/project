"""DCA 트리거·종료조건 검증 (07 계획 Step 5). DB 없이 도는 순수 함수 테스트.

DCA에서 돈이 직접 걸리는 지점은 "예산 상한을 넘지 않는가"와 "한 tick에 두 번 사지 않는가"라,
그 둘을 특히 촘촘히 본다.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.strategy_engine.dca import (
    EXTRA_BUY,
    SCHEDULED_BUY,
    evaluate,
    is_finished,
    next_schedule,
    period_delta,
    read_state,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
INVEST = Decimal("1000000")
PARAMS = {
    "interval": "1d",
    "buy_period": "week",
    "amount_per_buy": 100000,
    "end_condition": "count",
    "max_count": 10,
}


def _state(**overrides) -> dict:
    base = {
        "executed_count": 0,
        "next_buy_at": None,
        "last_buy_price": None,
        "spent_amount": "0",
    }
    base.update(overrides)
    return base


# ── 상태 읽기·스케줄 ───────────────────────────────────────────────────────


def test_read_state_fills_defaults_for_fresh_slot():
    """슬롯을 막 켠 시점에는 state.dca가 아예 없다 — 기본값으로 채워 읽어야 한다."""
    assert read_state({}) == _state()
    assert read_state(None) == _state()


def test_period_delta_maps_each_period():
    assert period_delta({"buy_period": "day"}) == timedelta(days=1)
    assert period_delta({"buy_period": "week"}) == timedelta(weeks=1)
    assert period_delta({"buy_period": "month"}) == timedelta(days=30)  # 구현 고정값


def test_next_schedule_counts_from_now_not_from_previous_slot():
    """워커가 한동안 멈췄다 살아나도 밀린 횟수를 몰아 사지 않도록 now 기준으로 민다."""
    assert next_schedule(NOW, PARAMS) == NOW + timedelta(weeks=1)


# ── 정기 매수 트리거 ───────────────────────────────────────────────────────


def test_first_evaluation_buys_immediately():
    """next_buy_at이 없으면 "지금이 첫 회차" — 슬롯을 켠 시점부터 분할매수가 시작된다."""
    intents = evaluate(NOW, Decimal("100"), _state(), PARAMS, INVEST)

    assert len(intents) == 1
    assert intents[0].side == "buy"
    assert intents[0].amount == Decimal("100000")
    assert intents[0].reason == SCHEDULED_BUY


def test_waits_until_scheduled_time():
    future = (NOW + timedelta(days=3)).isoformat()
    assert evaluate(NOW, Decimal("100"), _state(next_buy_at=future), PARAMS, INVEST) == []


def test_buys_when_scheduled_time_has_passed():
    past = (NOW - timedelta(seconds=1)).isoformat()
    intents = evaluate(NOW, Decimal("100"), _state(next_buy_at=past), PARAMS, INVEST)
    assert [i.reason for i in intents] == [SCHEDULED_BUY]


# ── 추가 매수 ─────────────────────────────────────────────────────────────


def _extra_params(**overrides) -> dict:
    return {**PARAMS, "extra_buy_enabled": True, "extra_buy_drop_pct": 10, **overrides}


def _waiting_state(**overrides) -> dict:
    """정기 매수는 아직 멀었고 직전 매수가가 100인 상태."""
    defaults = {
        "next_buy_at": (NOW + timedelta(days=3)).isoformat(),
        "last_buy_price": "100",
        "executed_count": 1,
        "spent_amount": "100000",
    }
    return _state(**{**defaults, **overrides})


def test_extra_buy_fires_on_drop_from_last_buy_price():
    intents = evaluate(NOW, Decimal("89"), _waiting_state(), _extra_params(), INVEST)
    assert [i.reason for i in intents] == [EXTRA_BUY]


def test_extra_buy_does_not_fire_above_threshold():
    """-10% 기준인데 -9%면 아직 아니다."""
    assert evaluate(NOW, Decimal("91"), _waiting_state(), _extra_params(), INVEST) == []


def test_extra_buy_respects_disabled_option():
    disabled = {**PARAMS, "extra_buy_enabled": False, "extra_buy_drop_pct": 10}
    assert evaluate(NOW, Decimal("50"), _waiting_state(), disabled, INVEST) == []


def test_extra_buy_needs_a_previous_buy_price():
    """한 번도 산 적이 없으면 기준점이 없어 추가매수가 성립하지 않는다."""
    state = _state(next_buy_at=(NOW + timedelta(days=3)).isoformat())
    assert evaluate(NOW, Decimal("1"), state, _extra_params(), INVEST) == []


def test_scheduled_buy_wins_when_both_would_fire():
    """한 tick에 두 건을 내면 예산이 예상보다 빨리 소진된다 — 정기 매수 하나만 낸다."""
    state = _waiting_state(next_buy_at=(NOW - timedelta(seconds=1)).isoformat())
    intents = evaluate(NOW, Decimal("50"), state, _extra_params(), INVEST)

    assert len(intents) == 1
    assert intents[0].reason == SCHEDULED_BUY


# ── 종료조건·예산 상한 ─────────────────────────────────────────────────────


def test_stops_after_max_count():
    state = _state(executed_count=10, spent_amount="0")
    assert is_finished(state, PARAMS, INVEST) is True
    assert evaluate(NOW, Decimal("100"), state, PARAMS, INVEST) == []


def test_count_condition_still_running_below_max():
    assert is_finished(_state(executed_count=9), PARAMS, INVEST) is False


def test_budget_cap_applies_even_with_count_condition():
    """invest_amount는 종료조건과 무관한 총 상한이다 (06-backtesting.md 2.4-1절) —
    횟수가 남아 있어도 예산을 넘길 수 없다."""
    state = _state(executed_count=1, spent_amount="950000")  # 남은 예산 50,000 < 회당 100,000
    assert is_finished(state, PARAMS, INVEST) is True
    assert evaluate(NOW, Decimal("100"), state, PARAMS, INVEST) == []


def test_budget_condition_stops_when_exhausted():
    budget_params = {**PARAMS, "end_condition": "budget"}
    state = _state(executed_count=99, spent_amount="950000")

    assert is_finished(state, budget_params, INVEST) is True
    # 아직 예산이 남아 있으면 횟수와 무관하게 계속 산다.
    assert is_finished(_state(executed_count=99, spent_amount="500000"), budget_params, INVEST) is False


def test_extra_buy_also_blocked_by_budget_cap():
    """추가매수 옵션으로 상한을 우회하지 못한다."""
    state = _waiting_state(spent_amount="950000")
    assert evaluate(NOW, Decimal("50"), state, _extra_params(), INVEST) == []
