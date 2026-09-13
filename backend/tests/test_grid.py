"""그리드 격자 산술과 매매 트리거 검증 (07 계획 Step 4). DB 없이 도는 순수 함수 테스트.

기준 격자는 전부 아래 값을 쓴다 — 손으로 따라가기 쉬운 수치로 골랐다:

    하한 100 / 상한 200 / 4칸  →  step 25
      매수 라인   [100, 125, 150, 175]
      매도 목표   [125, 150, 175, 200]
      라인당 배분 invest_amount / 4
"""

from decimal import Decimal

from app.strategy_engine.grid import (
    allocation_per_line,
    build_line_prices,
    drain_lines,
    evaluate,
    initial_lines,
    is_below_lower_bound,
    lines_match_params,
    reduce_line_quantity,
    sell_target_price,
    step_size,
)

PARAMS = {"lower_price": 100, "upper_price": 200, "grid_count": 4}
INVEST = Decimal("1000000")


def _lines(*filled_flags: bool, quantity: str = "0.5") -> list[dict]:
    prices = build_line_prices(PARAMS)
    return [
        {"price": str(price), "filled": filled, "quantity": quantity if filled else "0"}
        for price, filled in zip(prices, filled_flags)
    ]


# ── 격자 산술 ──────────────────────────────────────────────────────────────


def test_step_size_divides_range_by_grid_count():
    assert step_size(PARAMS) == Decimal("25")


def test_build_line_prices_excludes_upper_bound():
    """격자 4칸이면 매수 라인은 4개이고, 상한가는 최상단 라인의 매도 목표라 라인에 없다."""
    assert build_line_prices(PARAMS) == [
        Decimal("100.00000000"),
        Decimal("125.00000000"),
        Decimal("150.00000000"),
        Decimal("175.00000000"),
    ]


def test_sell_target_is_one_step_above_its_line():
    assert sell_target_price(PARAMS, 0) == Decimal("125.00000000")
    assert sell_target_price(PARAMS, 3) == Decimal("200.00000000")  # 최상단 라인의 목표 = 상한가


def test_allocation_splits_invest_amount_across_lines():
    """invest_amount는 전체 격자에 배분할 총 자금 상한이다 (06-backtesting.md 2.4-1절)."""
    allocation = allocation_per_line(INVEST, PARAMS)
    assert allocation == Decimal("250000")
    assert allocation * PARAMS["grid_count"] == INVEST  # 전 라인이 차면 정확히 배정액


def test_initial_lines_are_all_empty():
    lines = initial_lines(PARAMS)
    assert len(lines) == 4
    assert all(line["filled"] is False and line["quantity"] == "0" for line in lines)


def test_lines_match_params_detects_param_change():
    """OFF 상태에서 상한/하한/격자 수를 바꾸면 기존 라인은 의미를 잃는다 — 워커가 이걸로 감지한다."""
    lines = initial_lines(PARAMS)
    assert lines_match_params(lines, PARAMS) is True
    assert lines_match_params(lines, {**PARAMS, "grid_count": 5}) is False
    assert lines_match_params(lines, {**PARAMS, "lower_price": 90}) is False
    assert lines_match_params(None, PARAMS) is False


def test_is_below_lower_bound():
    assert is_below_lower_bound(Decimal("99.99"), PARAMS) is True
    assert is_below_lower_bound(Decimal("100"), PARAMS) is False


# ── 매수 트리거 ────────────────────────────────────────────────────────────


def test_buys_every_line_the_price_has_fallen_through():
    """가격이 130이면 그 위 라인(150·175)은 이미 관통한 것이므로 둘 다 매수 대상이다."""
    intents = evaluate(Decimal("130"), _lines(False, False, False, False), PARAMS, INVEST)

    assert [(i.side, i.grid_line_index) for i in intents] == [("buy", 2), ("buy", 3)]


def test_does_not_buy_lines_below_current_price():
    """가격 180 — 아직 175까지 내려오지 않았으므로 살 라인이 없다."""
    assert evaluate(Decimal("180"), _lines(False, False, False, False), PARAMS, INVEST) == []


def test_does_not_buy_already_filled_lines():
    intents = evaluate(Decimal("130"), _lines(False, False, True, True), PARAMS, INVEST)
    assert [i for i in intents if i.side == "buy"] == []


def test_does_not_buy_below_lower_bound():
    """하한가 아래는 그리드가 다루기로 한 구간이 아니다 — 이 방어가 없으면 이탈 순간 전
    라인이 한꺼번에 체결돼 배정액을 다 써버린다."""
    assert evaluate(Decimal("90"), _lines(False, False, False, False), PARAMS, INVEST) == []


# ── 매도 트리거 ────────────────────────────────────────────────────────────


def test_sells_filled_line_when_price_reaches_its_target():
    """라인 100(목표 125)과 라인 125(목표 150)를 든 채 가격이 160이면 둘 다 실현 대상이다."""
    intents = evaluate(Decimal("160"), _lines(True, True, False, False), PARAMS, INVEST)
    sells = [(i.side, i.grid_line_index, i.quantity) for i in intents if i.side == "sell"]

    assert sells == [("sell", 0, Decimal("0.5")), ("sell", 1, Decimal("0.5"))]


def test_holds_filled_line_below_its_target():
    """라인 150의 목표는 175 — 가격 160에서는 아직 실현하지 않는다."""
    intents = evaluate(Decimal("160"), _lines(False, False, True, False), PARAMS, INVEST)
    assert [i for i in intents if i.side == "sell"] == []


def test_sells_come_before_buys_in_the_same_evaluation():
    """같은 평가에서 매도와 매수가 함께 나오면 먼저 팔아 원화를 확보해야 매수가 잔고 부족으로
    스킵될 확률이 낮다."""
    # 가격 160: 라인 0(목표 125)·1(목표 150) 실현, 라인 3(175)은 아직 매수 구간
    intents = evaluate(Decimal("160"), _lines(True, True, False, False), PARAMS, INVEST)

    assert [i.side for i in intents] == ["sell", "sell", "buy"]
    assert intents[-1].grid_line_index == 3


# --- 덜 팔렸을 때의 라인 갱신 -----------------------------------------------
#
# 실매매에서는 슬롯이 팔려는 양보다 실제 가용 수량이 적을 수 있다(같은 코인의 수동 미체결
# 매도 등). 그때 라인을 통째로 비우면 `Σ lines == state.position` 불변식이 깨지고, 그 라인이
# 다시 매수 대상이 되어 이미 들고 있는 몫을 또 산다.


def _filled(*quantities) -> list[dict]:
    lines = initial_lines(PARAMS)
    return [
        {**line, "filled": Decimal(str(q)) > 0, "quantity": str(q)}
        for line, q in zip(lines, quantities)
    ]


def _total(lines) -> Decimal:
    return sum((Decimal(line["quantity"]) for line in lines if line["filled"]), Decimal(0))


def test_partial_sell_leaves_the_remainder_on_the_line():
    """라인 수량보다 적게 팔리면 남은 만큼이 라인에 그대로 남는다."""
    lines = _filled(0, 0, "0.5", 0)

    updated = reduce_line_quantity(lines, 2, Decimal("0.3"))

    assert updated[2]["filled"] is True
    assert Decimal(updated[2]["quantity"]) == Decimal("0.2")


def test_full_sell_empties_the_line():
    """전량 팔리면 지금까지대로 빈 라인이 된다."""
    lines = _filled(0, 0, "0.5", 0)

    updated = reduce_line_quantity(lines, 2, Decimal("0.5"))

    assert updated[2]["filled"] is False
    assert updated[2]["quantity"] == "0"


def test_selling_more_than_the_line_holds_does_not_go_negative():
    """라인 수량보다 많이 팔린 값이 들어와도 음수로 남지 않는다."""
    updated = reduce_line_quantity(_filled(0, 0, "0.5", 0), 2, Decimal("0.9"))

    assert updated[2]["filled"] is False
    assert Decimal(updated[2]["quantity"]) == Decimal(0)


def test_reduce_keeps_the_line_price_untouched():
    """라인 가격은 격자 레벨이라 건드리면 안 된다 — lines_match_params가 이 값을 본다."""
    lines = _filled(0, 0, "0.5", 0)

    updated = reduce_line_quantity(lines, 2, Decimal("0.3"))

    assert lines_match_params(updated, PARAMS)


def test_drain_takes_from_the_highest_priced_lines_first():
    """청산은 라인 지정이 없다 — 높은 가격 라인부터 뺀다 (그리드가 위에서부터 파는 구조)."""
    lines = _filled(0, "0.2", "0.3", "0.4")

    drained = drain_lines(lines, Decimal("0.5"))

    assert Decimal(drained[3]["quantity"]) == Decimal(0)  # 175 라인이 먼저 비었다
    assert Decimal(drained[2]["quantity"]) == Decimal("0.2")  # 150에서 0.1만 더 뺐다
    assert Decimal(drained[1]["quantity"]) == Decimal("0.2")  # 125는 그대로
    assert _total(drained) == Decimal("0.4")  # 0.9 - 0.5


def test_drain_of_the_whole_position_empties_everything():
    """전량 팔렸으면 라인이 전부 빈다."""
    drained = drain_lines(_filled(0, "0.2", "0.3", "0.4"), Decimal("0.9"))

    assert _total(drained) == Decimal(0)
    assert all(line["filled"] is False for line in drained)
