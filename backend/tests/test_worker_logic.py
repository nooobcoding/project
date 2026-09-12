"""워커의 순수 판단 로직 검증 (07 계획 Step 2B). DB·네트워크 없이 돈다.

주문 수량 산정은 돈이 직접 걸리는 계산이라 경계값을 특히 촘촘히 본다. 손절·익절 판정은
`strategy_engine/exits.py`로 옮겨졌고 검증도 tests/test_exits.py로 따라갔다 (06 계획 A-1).

`calc_buy_quantity`는 실제 정의가 `strategy_engine/costs.py`에 있지만(백테스팅과 공유), 워커
경로로 들어오는 호출이 그대로 유지되는지까지 함께 보기 위해 워커 모듈에서 임포트한다.
"""

from decimal import Decimal

from app.strategy_engine.worker import calc_buy_quantity

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
