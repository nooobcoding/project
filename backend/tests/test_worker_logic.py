"""워커의 순수 판단 로직 검증 (07 계획 Step 2B). DB·네트워크 없이 돈다.

주문 수량 산정과 손절·익절 판정은 돈이 직접 걸리는 계산이라 경계값을 특히 촘촘히 본다.
"""

from decimal import Decimal

from app.strategy_engine.worker import calc_buy_quantity, decide_exit

FEE_RATE = Decimal("0.0005")


# ── 매수 수량 산정 ──────────────────────────────────────────────────────────


def test_calc_buy_quantity_total_cost_never_exceeds_invest_amount():
    """수수료까지 포함한 총 지출이 배정액을 넘지 않아야 한다 (01-erd.md 3.2절)."""
    invest_amount = Decimal("1000000")
    price = Decimal("107500000")

    quantity = calc_buy_quantity(invest_amount, price, FEE_RATE)
    total_cost = price * quantity * (1 + FEE_RATE)

    assert total_cost <= invest_amount


def test_calc_buy_quantity_rounds_down_to_eight_decimals():
    """orders.quantity가 NUMERIC(28,8)이므로 8자리로 내림한다.

    1,000,000 / (107,500,000 × 1.0005) = 0.009297674… → 0.00929767.
    이 수량의 총 지출은 999,999.27원이고, 마지막 자리를 하나만 올리면(0.00929768)
    1,000,000.35원이 되어 배정액을 넘는다 — 내림이어야 하는 이유다.
    """
    quantity = calc_buy_quantity(Decimal("1000000"), Decimal("107500000"), FEE_RATE)

    assert quantity == Decimal("0.00929767")
    assert quantity.as_tuple().exponent == -8

    one_step_up = quantity + Decimal("0.00000001")
    assert Decimal("107500000") * one_step_up * (1 + FEE_RATE) > Decimal("1000000")


def test_calc_buy_quantity_returns_zero_when_price_too_high():
    """배정액이 1사토시 값어치도 안 되면 0 — 호출자가 주문을 건너뛴다."""
    assert calc_buy_quantity(Decimal("100"), Decimal("100000000000000"), FEE_RATE) == Decimal(0)


def test_calc_buy_quantity_guards_zero_price():
    """시세 캐시가 0을 주는 이상 상황에서 0으로 나누지 않는다."""
    assert calc_buy_quantity(Decimal("1000000"), Decimal("0"), FEE_RATE) == Decimal(0)


# ── 손절·익절 판정 ──────────────────────────────────────────────────────────


def test_decide_exit_take_profit_on_reaching_threshold():
    """진입가 100,000 / 익절 5% → 105,000 도달 시 익절 (06-backtesting.md 2.5절)."""
    assert decide_exit(Decimal("100000"), Decimal("105000"), None, Decimal("5")) == "take_profit"


def test_decide_exit_stop_loss_on_reaching_threshold():
    """손절 기준은 양수로 저장되고 -X% 도달 시 발동한다."""
    assert decide_exit(Decimal("100000"), Decimal("95000"), Decimal("5"), None) == "stop_loss"


def test_decide_exit_none_within_band():
    assert decide_exit(Decimal("100000"), Decimal("102000"), Decimal("5"), Decimal("5")) is None


def test_decide_exit_ignores_unset_thresholds():
    """손절·익절을 설정하지 않은 슬롯은 아무리 움직여도 청산하지 않는다."""
    assert decide_exit(Decimal("100000"), Decimal("10"), None, None) is None
    assert decide_exit(Decimal("100000"), Decimal("100000000"), None, None) is None


def test_decide_exit_take_profit_wins_when_both_would_trigger():
    """설정이 이상해 둘 다 걸리는 경우(익절≤0 등)에도 판정이 흔들리지 않게 익절을 먼저 본다."""
    assert decide_exit(Decimal("100000"), Decimal("105000"), Decimal("-100"), Decimal("5")) == "take_profit"


def test_decide_exit_guards_zero_average_price():
    """평단 0(포지션이 비정상)일 때 0으로 나누지 않는다."""
    assert decide_exit(Decimal("0"), Decimal("100"), Decimal("5"), Decimal("5")) is None
